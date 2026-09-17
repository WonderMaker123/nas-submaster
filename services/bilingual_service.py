# -*- coding: utf-8 -*-
"""
双语字幕生成与媒体服务器命名规范工具
"""
from pathlib import Path
from typing import List, Optional
from services.translator import parse_srt_file, SubtitleEntry


def generate_bilingual_srt(
    orig_srt_path: str,
    trans_srt_path: str,
    output_path: str,
    primary: str = "trans"  # 'trans' (上中下英) 或 'orig' (上英下中)
) -> bool:
    """
    将原始语言字幕与翻译语言字幕合并为双语字幕
    """
    try:
        orig_entries = parse_srt_file(orig_srt_path)
        trans_entries = parse_srt_file(trans_srt_path)

        if not orig_entries or not trans_entries:
            return False

        # 以翻译字幕或原始字幕为基准对齐
        merged_entries = []
        trans_dict = {e.index: e for e in trans_entries}

        for orig in orig_entries:
            matched_trans = trans_dict.get(orig.index)
            orig_text = orig.text.strip()

            if matched_trans and matched_trans.text.strip():
                trans_text = matched_trans.text.strip()
                if primary == "trans":
                    combined_text = f"{trans_text}\n{orig_text}"
                else:
                    combined_text = f"{orig_text}\n{trans_text}"
            else:
                combined_text = orig_text

            merged_entries.append(
                SubtitleEntry(
                    index=orig.index,
                    start_time=orig.start_time,
                    end_time=orig.end_time,
                    text=combined_text
                )
            )

        # 写入文件
        lines = []
        for e in merged_entries:
            lines.append(f"{e.index}\n{e.start_time} --> {e.end_time}\n{e.text}\n")

        Path(output_path).write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[Bilingual] 合并双语字幕失败: {e}")
        return False


def get_subtitle_export_paths(
    media_file_path: str,
    target_lang: str,
    naming_standard: str = "standard"
) -> dict:
    """
    根据媒体服务器命名规范生成目标路径
    naming_standard:
      - 'standard': movie.zh-CN.srt, movie.zh-CN.bilingual.srt (Jellyfin/Plex 标准推荐)
      - 'emby': movie.chi.default.srt, movie.chi.bilingual.srt (Emby 规范)
      - 'simple': movie.zh.srt, movie.zh.bilingual.srt
    """
    p = Path(media_file_path)
    parent = p.parent
    stem = p.stem

    # 规范化语言标签
    if naming_standard == "emby":
        lang_tag = "chi" if target_lang.lower().startswith("zh") else target_lang
    elif naming_standard == "standard":
        lang_tag = "zh-CN" if target_lang.lower().startswith("zh") else target_lang
    else:
        lang_tag = target_lang

    return {
        "trans_srt": parent / f"{stem}.{lang_tag}.srt",
        "bilingual_srt": parent / f"{stem}.{lang_tag}.bilingual.srt",
        "lang_tag": lang_tag
    }
