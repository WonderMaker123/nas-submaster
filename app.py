#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAS 字幕管家 V7.0 - 重构版
主程序：仅负责 Streamlit UI 入口和页面路由
"""

import os
import streamlit as st
import logging

# 抑制 Tornado WebSocket 警告
logging.getLogger('tornado.application').setLevel(logging.ERROR)
logging.getLogger('tornado.access').setLevel(logging.ERROR)

# 导入核心模块
# 导入核心模块
from database.connection import init_database, get_db_connection
from core.config import ConfigManager
from core.worker import start_worker
# OLD: from ui.sidebar import render_sidebar
from ui.settings_modal import render_settings_dialog
from ui.pages.media_library import render_media_library_page
from ui.pages.task_queue import render_task_queue_page
from ui.styles import HERO_CSS


def check_auth(config_pwd: str) -> bool:
    """密码鉴权检查。如果未设置密码则直接放行；设置了则需验证输入"""
    if not config_pwd:
        return True
    
    if st.session_state.get("authenticated", False):
        return True

    # 居中渲染登录卡片
    st.markdown("<div style='height: 80px;'></div>", unsafe_allow_html=True)
    _, col_login, _ = st.columns([1, 1.2, 1])
    
    with col_login:
        with st.container():
            st.markdown(
                """
                <div style='text-align: center; margin-bottom: 24px;'>
                    <h2 style='margin-bottom: 8px;'>🔒 访问受限</h2>
                    <p style='color: #888; font-size: 14px;'>当前系统已启用安全密码防护，请输入密码后继续</p>
                </div>
                """,
                unsafe_allow_html=True
            )
            with st.form("login_form", clear_on_submit=False):
                pwd_input = st.text_input("安全访问密码", type="password", placeholder="请输入访问密码")
                submit = st.form_submit_button("进入系统", type="primary", use_container_width=True)
                
                if submit:
                    if pwd_input == config_pwd:
                        st.session_state.authenticated = True
                        st.rerun()
                    else:
                        st.error("密码错误，请重新输入")
    return False


# ============================================================================
# 主程序
# ============================================================================

def main():
    """主函数"""
    # 页面配置
    st.set_page_config(
        page_title="NAS 字幕管家",
        layout="wide"
    )
    
    # 应用样式
    st.markdown(HERO_CSS, unsafe_allow_html=True)
    
    # 密码鉴权检查
    cfg_mgr = ConfigManager()
    app_config = cfg_mgr.load()
    if not check_auth(app_config.web_password):
        return

    # Header 布局 (Logo + 标题 + 设置按钮) - 与媒体库工具栏对齐
    col_h1, col_h2, col_h3, col_logout, col_settings = st.columns([2.2, 1.3, 2.4, 0.7, 0.9])
    
    with col_h1:
        # 使用 base64 编码图片并用 flexbox 实现垂直居中
        import base64
        with open("assets/logo.png", "rb") as f:
            logo_base64 = base64.b64encode(f.read()).decode()
        
        st.markdown(
            f"""
            <div style='display: flex; align-items: center; gap: 16px;'>
                <img src='data:image/png;base64,{logo_base64}' style='height: 48px; width: 48px; object-fit: contain;' />
                <h1 style='margin: 0; font-size: 32px; font-weight: 700; line-height: 48px;'>NAS 字幕管家</h1>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    # 空列用于对齐
    with col_h2:
        pass
    with col_h3:
        pass
    with col_logout:
        if app_config.web_password:
            st.markdown("<div style='height: 12px'></div>", unsafe_allow_html=True)
            if st.button("🚪 锁定", help="注销退出，锁定页面", use_container_width=True):
                st.session_state.authenticated = False
                st.rerun()
        
    with col_settings:
        st.markdown("<div style='height: 12px'></div>", unsafe_allow_html=True) # Spacer
        if st.button("⚙️ 系统配置", help="打开系统设置", use_container_width=True):
            render_settings_dialog()
    
    # 获取调试模式状态 (从 session)
    debug_mode = st.session_state.get('debug_mode', False)
    
    # 渲染主页面（Tab 切换）
    tab1, tab2 = st.tabs(["媒体库", "任务队列"])
    
    with tab1:
        render_media_library_page(debug_mode)
    
    with tab2:
        render_task_queue_page()


# ============================================================================
# 入口点
# ============================================================================

if __name__ == "__main__":
    # 创建必要的目录
    os.makedirs("./data/models", exist_ok=True)
    
    # 初始化数据库
    init_database()
    
    # 启动后台工作器（仅启动一次）
    if 'worker_started' not in st.session_state:
        print("[Main] Starting worker thread...")
        start_worker()
        st.session_state.worker_started = True
        print("[Main] Worker thread started")
    
    # 运行主程序
    main()