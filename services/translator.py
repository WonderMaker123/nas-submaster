#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕翻译模块（重构版）
主要改进：
1. 使用 JSON 格式强制结构化输出
2. 智能分段策略（短视频整体翻译，长视频分场景）
3. 完善错误处理（不再静默失败）
4. 支持翻译质量检测和重试
5. 支持断点续译草稿缓存（中断/失败后重试不重译已完成批次，节省 token）
"""

import json
import os
import re
import time
from typing import List, Dict, Tuple, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from openai import OpenAI
from dataclasses import dataclass

from core.models import SubtitleEntry


@dataclass
class TranslationConfig:
    """翻译配置"""
    api_key: str
    base_url: str
    model_name: str
    target_language: str
    source_language: str = 'auto'
    max_lines_per_batch: int = 500  # 每批最多翻译多少行
    max_concurrent_batches: int = 3  # 最大并发批次请求数
    max_retries: int = 3
    timeout: int = 600


class TranslationError(Exception):
    """翻译错误基类"""
    pass


class APIError(TranslationError):
    """API 调用错误"""
    pass


class ParseError(TranslationError):
    """解析错误"""
    pass


class SubtitleTranslator:
    """字幕翻译器"""
    
    # 语言名称映射
    LANG_NAMES = {
        'zh': '中文 (Simplified Chinese)',
        'en': '英语 (English)',
        'ja': '日语 (Japanese)',
        'ko': '韩语 (Korean)',
        'fr': '法语 (French)',
        'de': '德语 (German)',
        'ru': '俄语 (Russian)',
        'es': '西班牙语 (Spanish)'
    }
    
    def __init__(self, config: TranslationConfig, progress_callback=None, prompt_template=None, checkpoint_path: Optional[str] = None):
        """
        初始化翻译器

        Args:
            config: 翻译配置
            progress_callback: 进度回调函数 (current, total, message)
            prompt_template: 提示词模板，如果为 None 则使用内置默认提示词
            checkpoint_path: 断点续译草稿文件路径（可选，存在则启用断点暂存）
        """
        self.config = config
        self.progress_callback = progress_callback
        self.prompt_template = prompt_template
        self.checkpoint_path = checkpoint_path

        # 初始化 OpenAI 客户端
        # Ollama 不需要 API Key，但 openai 库要求非空值
        api_key = config.api_key
        if not api_key or not api_key.strip():
            api_key = "ollama"
        elif "ollama" in config.base_url.lower():
            api_key = "ollama"

        self.client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.timeout,
        )
    
    def _update_progress(self, current_lines: int, total_lines: int, message: str):
        """
        v1.8.1: 上报翻译进度

        Args:
            current_lines: 已翻译条数
            total_lines: 总条数
            message: 进度消息

        Note:
            - stage 固定为 'translate'（在 worker 那边决定）
            - stage_progress 上报 current_lines（让 UI 显示 "已翻译 X/Y 条"）
            - 不再上报百分比 —— LLM 流式输出长度不可预测，强行算会跳
        """
        if self.progress_callback:
            # 第一参数是 stage ('translate' 固定), 第二参数是 current_lines
            # worker 拿到的就是 (stage, stage_progress, message)
            self.progress_callback("translate", current_lines, message)
    
    def _get_target_lang_name(self) -> str:
        """获取目标语言名称"""
        return self.LANG_NAMES.get(
            self.config.target_language, 
            self.config.target_language
        )
    
    def _build_translation_prompt(
        self,
        entries: List[SubtitleEntry],
        context_before: Optional[str] = None,
        context_after: Optional[str] = None
    ) -> str:
        """
        构建翻译 prompt（使用 JSON 格式）

        Args:
            entries: 要翻译的字幕条目
            context_before: 前文上下文（仅供参考，不翻译）
            context_after: 后文上下文（仅供参考，不翻译）
        """
        target_lang = self._get_target_lang_name()

        # 构建输入 JSON
        input_json = [
            {"line": i+1, "text": entry.text}
            for i, entry in enumerate(entries)
        ]

        # 上下文提示
        context_hint = ""
        if context_before or context_after:
            context_hint = "\n\nCONTEXT (for reference only, helps understand the flow):"
            if context_before:
                context_hint += f"\nPrevious line: \"{context_before}\""
            if context_after:
                context_hint += f"\nNext line: \"{context_after}\""

        # 使用用户配置的提示词模板或内置默认
        if self.prompt_template:
            role = self.prompt_template.role
            rules = self.prompt_template.rules
            style_guide = self.prompt_template.style_guide
        else:
            role = "You are a professional subtitle translator."
            rules = "1. Keep translations natural and concise\n2. Preserve character names and proper nouns\n3. DO NOT add punctuation unless present in original\n4. Output valid JSON array"
            style_guide = "Subtitle style: concise, readable"

        prompt = f"""{role} Translate the following dialogue to {target_lang}.

STYLE GUIDE:
{style_guide}

RULES:
{rules}

OUTPUT FORMAT:
Output MUST be valid JSON array with EXACTLY {len(entries)} objects.
Each object MUST have "line" (number) and "translation" (string) fields.{context_hint}

INPUT ({len(entries)} lines):
{json.dumps(input_json, ensure_ascii=False, indent=2)}

OUTPUT (valid JSON array with ALL {len(entries)} items):
[
  {{"line": 1, "translation": "..."}},
  {{"line": 2, "translation": "..."}},
  {{"line": 3, "translation": "..."}},
  {{"line": {len(entries)}, "translation": "..."}}
]

Now output the COMPLETE JSON array (no extra text, no abbreviations):"""

        return prompt
    
    def _parse_translation_response(
        self, 
        response: str, 
        expected_count: int
    ) -> List[str]:
        """
        解析翻译响应（JSON 格式）- 增强版
        
        Args:
            response: API 返回的原始响应
            expected_count: 期望的翻译数量
        
        Returns:
            翻译文本列表
        
        Raises:
            ParseError: 解析失败
        """
        # 1. 过滤思考模型（如 DeepSeek-R1, Qwen-Max-Thinking, Kimi-k1.5 等）的 <think> 标签内容
        if '<think>' in response:
            response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
        elif '</think>' in response:
            # 某些模型可能省略 <think> 直接返回结尾 </think>
            response = response.split('</think>', 1)[-1].strip()

        # 2. 清理 markdown 代码块格式 (```json ... ```)
        response = response.strip()
        if "```" in response:
            # 使用正则优先提取代码块内的 json 数组
            match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response, re.DOTALL)
            if match:
                response = match.group(1).strip()
            else:
                lines = response.split('\n')
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = '\n'.join(lines).strip()
        
        # 3. 截取首尾匹配的 JSON 数组（避免开头问候语或末尾附带说明文本）
        bracket_start = response.find('[')
        bracket_end = response.rfind(']')
        if bracket_start != -1 and bracket_end != -1 and bracket_end > bracket_start:
            response = response[bracket_start:bracket_end + 1]
        elif bracket_start != -1:
            # 尾部截断，取到结尾
            response = response[bracket_start:]
        
        # 检查是否包含省略符号 "..."
        if '...' in response and '"...' not in response:
            # 如果 ... 出现在非字符串中（即作为省略符号），说明 AI 返回了缩略格式
            raise ParseError(
                f"AI 返回了省略格式（包含 ...），请求的 {expected_count} 条翻译未完整返回。"
                "这通常是因为内容过长，请降低 max_lines_per_batch 配置。"
            )
        
        # 尝试解析 JSON
        data = None
        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            # JSON 解析失败，尝试修复常见问题
            stripped = response.rstrip()

            # 尝试 1: 移除尾部逗号（如果有）
            if stripped.endswith(',]'):
                try:
                    data = json.loads(stripped[:-2] + ']')
                except json.JSONDecodeError:
                    pass

            # 尝试 2: 补全缺失的闭合括号
            if data is None and not stripped.endswith(']'):
                try:
                    data = json.loads(stripped + ']')
                except json.JSONDecodeError:
                    pass

            # 如果仍然失败，抛出详细错误
            if data is None:
                raise ParseError(
                    f"JSON 解析失败: {e}\n"
                    f"原始响应预览: {response[:300]}...\n"
                    f"响应长度: {len(response)} 字符"
                )
        
        # 验证格式
        if not isinstance(data, list):
            raise ParseError(f"期望 JSON 数组，实际得到: {type(data).__name__}")
        
        if len(data) != expected_count:
            raise ParseError(
                f"翻译数量不匹配: 期望 {expected_count} 条，实际 {len(data)} 条\n"
                f"提示: 如果 AI 返回了省略格式，请降低 max_lines_per_batch 配置（当前可能过大）"
            )
        
        # 提取翻译文本
        translations = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ParseError(f"第 {i+1} 项不是字典: {item}")
            
            if 'translation' not in item:
                raise ParseError(f"第 {i+1} 项缺少 'translation' 字段: {item}")
            
            line_num = item.get('line', i+1)
            if line_num != i+1:
                raise ParseError(
                    f"第 {i+1} 项的 line 值错误: 期望 {i+1}，实际 {line_num}"
                )
            
            translations.append(str(item['translation']).strip())
        
        return translations
    
    def _split_and_translate(
        self,
        entries: List[SubtitleEntry],
        context_before: Optional[str] = None,
        context_after: Optional[str] = None
    ) -> List[SubtitleEntry]:
        """
        将批次拆分为两半分别翻译（用于 AI 返回省略格式时的降级处理）
        """
        print(f"[智能降级] 批次过大 ({len(entries)} 行)，自动拆分为 2 个子批次")
        mid = len(entries) // 2
        ctx_mid_after = entries[mid].text if mid < len(entries) else None
        ctx_mid_before = entries[mid - 1].text if mid > 0 else None
        batch1 = self._translate_batch(entries[:mid], context_before, ctx_mid_after)
        batch2 = self._translate_batch(entries[mid:], ctx_mid_before, context_after)
        return batch1 + batch2

    def _translate_batch(
        self,
        entries: List[SubtitleEntry],
        context_before: Optional[str] = None,
        context_after: Optional[str] = None,
    ) -> List[SubtitleEntry]:
        """
        翻译一批字幕（带重试，检测到省略格式时自动拆分降级）

        Args:
            entries: 要翻译的字幕条目
            context_before: 前文上下文
            context_after: 后文上下文

        Returns:
            翻译后的字幕条目

        Raises:
            APIError: API 调用失败
            ParseError: 解析失败
        """
        prompt = self._build_translation_prompt(entries, context_before, context_after)

        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    timeout=self.config.timeout
                )

                raw_response = response.choices[0].message.content.strip()
                translations = self._parse_translation_response(raw_response, len(entries))

                # 构建翻译后的字幕条目
                translated_entries = []
                for entry, translation in zip(entries, translations):
                    translated_entries.append(
                        SubtitleEntry(
                            index=entry.index,
                            timecode=entry.timecode,
                            text=translation
                        )
                    )

                return translated_entries

            except ParseError as e:
                last_error = e
                error_msg = str(e)

                # 检测到省略格式：直接拆分，不再重试当前批次
                if ("省略格式" in error_msg or "..." in error_msg) and len(entries) > 50:
                    print(f"[翻译] 检测到省略格式，批次大小: {len(entries)} 行，触发拆分降级")
                    return self._split_and_translate(entries, context_before, context_after)

                if attempt < self.config.max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"[翻译] 解析失败，{wait_time}秒后重试 ({attempt+1}/{self.config.max_retries}): {error_msg[:100]}")
                    time.sleep(wait_time)
                else:
                    raise

            except Exception as e:
                last_error = APIError(f"API 调用失败: {e}")
                if attempt < self.config.max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"[翻译] API 错误，{wait_time}秒后重试 ({attempt+1}/{self.config.max_retries}): {e}")
                    time.sleep(wait_time)
                else:
                    raise last_error

        # 不应该到达这里
        raise last_error or TranslationError("翻译失败，原因未知")

    def _load_checkpoint(self) -> Dict[int, List[dict]]:
        """从断点草稿中加载已翻译完成的批次"""
        if not self.checkpoint_path or not os.path.exists(self.checkpoint_path):
            return {}
        try:
            with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                return {int(k): v for k, v in raw_data.items()}
        except Exception as e:
            print(f"[翻译断点] 加载草稿失败，将重新翻译: {e}")
            return {}

    def _save_checkpoint_batch(self, b_num: int, translated_batch: List[SubtitleEntry], checkpoint_lock: threading.Lock):
        """保存单个已完成批次到断点草稿文件中"""
        if not self.checkpoint_path:
            return
        with checkpoint_lock:
            try:
                current_data = self._load_checkpoint()
                current_data[b_num] = [
                    {"index": e.index, "timecode": e.timecode, "text": e.text}
                    for e in translated_batch
                ]
                with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
                    json.dump(current_data, f, ensure_ascii=False)
            except Exception as e:
                print(f"[翻译断点] 写入草稿失败: {e}")

    def translate_subtitles(
        self, 
        entries: List[SubtitleEntry]
    ) -> List[SubtitleEntry]:
        """
        翻译字幕（智能分段 + 并发加速 + 断点续译支持）
        
        Args:
            entries: 原始字幕条目列表
        
        Returns:
            翻译后的字幕条目列表
        """
        if not entries:
            return []
        
        total_lines = len(entries)
        max_batch = self.config.max_lines_per_batch
        
        # 短视频：一次性翻译
        if total_lines <= max_batch:
            self._update_progress(0, total_lines, f"开始翻译 {total_lines} 行字幕...")

            try:
                translated = self._translate_batch(entries)
                self._update_progress(total_lines, total_lines, "翻译完成！")
                return translated
            except Exception:
                raise
        
        # 长视频：分批翻译（支持多批次并发请求 + 断点草稿续译，大幅提速与防 token 浪费）
        total_batches = (total_lines + max_batch - 1) // max_batch
        max_workers = max(1, getattr(self.config, 'max_concurrent_batches', 3))

        # 读取断点草稿缓存
        cached_batches = self._load_checkpoint()
        results_by_index = {}
        completed_lines = 0

        # 恢复草稿中的批次
        for b_num, raw_list in cached_batches.items():
            results_by_index[b_num] = [
                SubtitleEntry(index=item["index"], timecode=item["timecode"], text=item["text"])
                for item in raw_list
            ]
            completed_lines += len(results_by_index[b_num])

        if cached_batches:
            print(f"[翻译断点] 从草稿中恢复了 {len(cached_batches)}/{total_batches} 个批次，无需重复消耗 Token！")
            self._update_progress(
                completed_lines, total_lines,
                f"已从断点恢复 {completed_lines}/{total_lines} 行，继续翻译剩余批次..."
            )

        # 准备待翻译批次
        batches_info = []
        for i in range(0, total_lines, max_batch):
            batch_num = i // max_batch + 1
            if batch_num in results_by_index:
                continue  # 已从断点草稿加载，跳过网络调用

            batch = entries[i:i+max_batch]
            context_before = entries[i-1].text if i > 0 else None
            context_after = entries[i+max_batch].text if i+max_batch < total_lines else None
            batches_info.append((batch_num, i, batch, context_before, context_after))

        progress_lock = threading.Lock()
        checkpoint_lock = threading.Lock()

        def _process_one_batch(info):
            b_num, start_idx, b_entries, ctx_b, ctx_a = info
            try:
                translated_b = self._translate_batch(b_entries, ctx_b, ctx_a)
                # 写入断点草稿缓存
                self._save_checkpoint_batch(b_num, translated_b, checkpoint_lock)

                nonlocal completed_lines
                with progress_lock:
                    completed_lines += len(b_entries)
                    self._update_progress(
                        completed_lines,
                        total_lines,
                        f"已完成 {completed_lines}/{total_lines} 行（批次 {b_num}/{total_batches}）..."
                    )
                return b_num, translated_b
            except Exception as e:
                raise TranslationError(f"第 {b_num}/{total_batches} 批翻译失败: {e}")

        # 如果有未完成的批次需要请求
        if batches_info:
            if max_workers == 1:
                for info in batches_info:
                    b_num, translated_b = _process_one_batch(info)
                    results_by_index[b_num] = translated_b
            else:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(_process_one_batch, info) for info in batches_info]
                    for future in as_completed(futures):
                        b_num, translated_b = future.result()
                        results_by_index[b_num] = translated_b

        # 按原批次顺序重组结果
        translated_entries = []
        for b_num in range(1, total_batches + 1):
            if b_num in results_by_index:
                translated_entries.extend(results_by_index[b_num])
            else:
                raise TranslationError(f"批次 {b_num} 缺失，无法合成最终字幕")

        # 翻译完成，清理断点草稿文件
        if self.checkpoint_path and os.path.exists(self.checkpoint_path):
            try:
                os.remove(self.checkpoint_path)
            except Exception:
                pass

        self._update_progress(total_lines, total_lines, "翻译完成！")
        return translated_entries


# ============================================================================
# 辅助函数
# ============================================================================

def parse_srt_file(srt_path: str) -> List[SubtitleEntry]:
    """
    解析 SRT 文件
    
    Args:
        srt_path: SRT 文件路径
    
    Returns:
        字幕条目列表
    """
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    entries = []
    blocks = content.strip().split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            try:
                entries.append(
                    SubtitleEntry(
                        index=lines[0].strip(),
                        timecode=lines[1].strip(),
                        text='\n'.join(lines[2:]).strip()
                    )
                )
            except Exception as e:
                print(f"[警告] 跳过无效字幕块: {e}")
                continue
    
    return entries


def save_srt_file(entries: List[SubtitleEntry], output_path: str):
    """
    保存 SRT 文件
    
    Args:
        entries: 字幕条目列表
        output_path: 输出文件路径
    """
    lines = []
    for entry in entries:
        if not entry.text:
            continue
        lines.append(f"{entry.index}\n{entry.timecode}\n{entry.text}\n")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def translate_srt_file(
    input_path: str,
    config: TranslationConfig,
    output_path: Optional[str] = None,
    progress_callback=None,
    prompt_template=None,
    checkpoint_path: Optional[str] = None
) -> Tuple[bool, str]:
    """
    翻译 SRT 文件（高级封装）

    Args:
        input_path: 输入 SRT 文件路径
        config: 翻译配置
        output_path: 输出路径（默认：原文件名.{target_lang}.srt）
        progress_callback: 进度回调
        prompt_template: 提示词模板，如果为 None 则使用内置默认提示词
        checkpoint_path: 断点草稿文件路径

    Returns:
        (成功标志, 消息)
    """
    try:
        # 解析原始字幕
        entries = parse_srt_file(input_path)
        if not entries:
            return False, "字幕文件为空或格式错误"

        # 如果未显式提供草稿路径，默认在同目录下生成 .part.json
        if checkpoint_path is None:
            checkpoint_path = str(Path(input_path).with_suffix(f'.{config.target_language}.part.json'))

        # 执行翻译
        translator = SubtitleTranslator(config, progress_callback, prompt_template, checkpoint_path=checkpoint_path)
        translated_entries = translator.translate_subtitles(entries)

        # 生成输出路径
        if output_path is None:
            input_file = Path(input_path)
            output_path = str(
                input_file.parent /
                f"{input_file.stem}.{config.target_language}.srt"
            )

        # 保存翻译结果
        save_srt_file(translated_entries, output_path)

        return True, f"翻译完成，已保存到: {output_path}"

    except TranslationError as e:
        return False, str(e)
    except Exception as e:
        return False, f"未知错误: {e}"
