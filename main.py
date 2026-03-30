import streamlit as st
from streamlit_option_menu import option_menu
import json
import os
import time
import psutil
import socket
import asyncio
import sys
from cryptography.fernet import Fernet
import base64
import uuid
import subprocess
from login import execute_login
from task_handler import execute_video_task
from playwright.sync_api import sync_playwright   
from local_asr_worker import LocalASRWorker
from ramdisk import setup_ramdisk, remove_ramdisk
import tkinter as tk
from tkinter import filedialog



if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

 
CONFIG_FILE = "config.json"

def get_hardware_key():
     
    node = uuid.getnode()
    seed = str(node).encode()
     
    key = base64.urlsafe_b64encode(seed.ljust(32)[:32])
    return Fernet(key)

def encrypt(data):
    if not data: return ""
    f = get_hardware_key()
    return f.encrypt(data.encode()).decode()

def decrypt(encrypted_data):
    if not encrypted_data: return ""
    try:
        f = get_hardware_key()
        return f.decrypt(encrypted_data.encode()).decode()
    except:
         
        return encrypted_data

def load_config():
    """读取配置，供内存和 UI 使用（全部解密为明文）"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            try:
                c = json.load(f)
            except json.JSONDecodeError:
                c = {}
            
             
            if "history_urls" not in c or not isinstance(c.get("history_urls"), dict):
                old_list = c.get("history_urls", ["https://cvs.seu.edu.cn"])
                c["history_urls"] = {url: url for url in old_list}
            
             
            c["username"] = decrypt(c.get("username", ""))
            c["password"] = decrypt(c.get("password", ""))
            c["api_key"] = decrypt(c.get("api_key", ""))
            c["asr_api_key"] = decrypt(c.get("asr_api_key", ""))
            
            defaults = {
                "headless_mode": False,
                "need_subtitle": True,
                "need_ppt": False,
                "keep_media": False,
                "asr_engine": "本地模型 (Faster-Whisper)",
                "llm_engine": "DeepSeek (api.deepseek.com)",
                "target_url": "https://cvs.seu.edu.cn",
                "custom_asr_endpoints": {}, 
                "custom_llm_endpoints": {}
            }
            for k, v in defaults.items():
                if k not in c:
                    c[k] = v
            return c
            
    return {
        "username": "", "password": "", "target_url": "https://cvs.seu.edu.cn",
        "headless_mode": False, "need_subtitle": True, "need_ppt": False, "keep_media": False,
        "asr_engine": "本地模型 (Faster-Whisper)", "llm_engine": "DeepSeek (api.deepseek.com)",
        "history_urls": {"默认门户": "https://cvs.seu.edu.cn"}
    }

def save_config(data):
    """保存配置，强制对所有敏感字段进行全量加密拦截"""
    current = load_config()   
    current.update(data)      
    
     
    to_save = current.copy()
    
     
    to_save["username"] = encrypt(to_save.get("username", ""))
    to_save["password"] = encrypt(to_save.get("password", ""))
    to_save["api_key"] = encrypt(to_save.get("api_key", ""))
    to_save["asr_api_key"] = encrypt(to_save.get("asr_api_key", ""))
    os.makedirs(os.path.dirname(os.path.abspath(CONFIG_FILE)), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(to_save, f, ensure_ascii=False, indent=4)

def sync_state_to_config(key_name):
    """当 Streamlit 组件值改变时，自动同步到 json"""
    if key_name in st.session_state:
        new_val = st.session_state[key_name]
        save_config({key_name: new_val})

def get_public_ip():
    
    try:
         
        result = subprocess.run(
            ['curl', '-4', '-s', '--noproxy', '*', 'http://ifconfig.me'], 
            capture_output=True, 
            text=True, 
            timeout=3
        )
        return result.stdout.strip()
    except:
        return "出口受阻"
        
@st.fragment(run_every=5)  
def show_system_status_cards(url):
     
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
     
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        network_status = f"已连接 (IP: {local_ip})"
    except:
        network_status = "未连接网络"
    
    public_ip=get_public_ip()
    

     
    status_cols = st.columns(3)
    with status_cols[0]:
        with st.container(border=True):
            st.write("网络环境")
             
            if public_ip == "出口受阻":
                st.metric("已连接到网络:",f"{network_status.split("IP: ")[-1].strip(')') if 'IP: ' in network_status else network_status}")
            else:
                st.metric("已连接到网络:", public_ip)

    with status_cols[1]:
        with st.container(border=True):
            st.write("浏览器引擎")
            st.metric("当前:", "chromium")

    with status_cols[2]:
        with st.container(border=True):
            st.write("系统资源")
            m1, m2, m3 = st.columns(3)
            m1.metric("CPU", f"{cpu}%")
            m2.metric("内存", f"{mem}%")
            m3.metric("磁盘", f"{disk}%")

def select_folder():
    """静默调用 Windows 原生资源管理器"""
    root = tk.Tk()
    root.withdraw()   
    root.wm_attributes('-topmost', 1)   
    folder_path = filedialog.askdirectory(master=root, title="选择网课导出文件夹")
    root.destroy()
    return folder_path

def kill_orphaned_browsers():
    """物理强杀残留的 Playwright 和 Chromium 进程"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline')
            if not cmdline:
                continue
            cmd_str = ' '.join(cmdline).lower()
             
            if 'ms-playwright' in cmd_str or '--disable-blink-features=automationcontrolled' in cmd_str:
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def run_manual_init_login(target_url, username, password):
    """专用初始化函数：强制在主屏幕可见区域弹出窗口"""
    def get_time(): return time.strftime('%H:%M:%S')
    
    try:
        with sync_playwright() as p:
            yield f"[{get_time()}] 正在唤起可视化授权环境..."
            
            import os
            user_data_dir = os.path.join(os.getcwd(), "browser_data")
            
             
             
            browser_args = [
                "--disable-blink-features=AutomationControlled",
                "--window-position=0,0", 
                "--start-maximized"
            ]
            
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                no_viewport=True,  
                args=browser_args
            )
            
            page = context.pages[0] if context.pages else context.new_page()
            
            try:
                 
                 
                yield from execute_login(page, target_url, username, password)
                yield f"[{get_time()}] 授权成功！设备信任凭证已保存。"
            except Exception as e:
                yield f"[{get_time()}] 授权中断: {str(e)}"
            finally:
                time.sleep(2)
                context.close()
    except Exception as e:
        yield f"[{get_time()}] 引擎启动失败: {str(e)}"

def run_fetch_dates_pipeline(target_url, username, password, headless):
    """专门用于静默获取课程日期的探测管道"""
    from task_handler import fetch_dates_only
    def get_time(): return time.strftime('%H:%M:%S')
    
    try:
        with sync_playwright() as p:
            yield f"[{get_time()}] 启动探测浏览器内核 (持久化模式)..."
            
            import os
             
            user_data_dir = os.path.join(os.getcwd(), "browser_data")
            
             
            browser_args = ["--disable-blink-features=AutomationControlled"]
            
             
            if headless:
                actual_headless = False   
                browser_args.extend([
                    "--window-position=-32000,-32000",  
                    "--window-size=1920,1080"           
                ])
            else:
                actual_headless = False
                
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=actual_headless, 
                args=browser_args
            )
            
             
            page = context.pages[0] if context.pages else context.new_page()
            try:
                yield from execute_login(page, target_url, username, password)
                yield f"[{get_time()}] 登录成功，正在解析课程列表结构..."
                dates = fetch_dates_only(page)
                yield dates  
            except Exception as e:
                yield f"[{get_time()}] 探测中断: {str(e)}"
            finally:
                context.close()
    except Exception as e:
        yield f"[{get_time()}] 内核启动失败: {str(e)}"


def run_pipeline(target_url, username, password, headless, asr_worker, stop_event, need_subtitle, need_ppt, keep_media, target_date=None):
    def get_time(): return time.strftime('%H:%M:%S')
    task_name = f"Class_{int(time.time())}"
    
    try:
         
       with sync_playwright() as p:
            yield f"[{get_time()}] 启动探测浏览器内核 (持久化模式)..."
            
            import os
             
            user_data_dir = os.path.join(os.getcwd(), "browser_data")
            
             
            browser_args = ["--disable-blink-features=AutomationControlled"]
            
             
            if headless:
                actual_headless = False   
                browser_args.extend([
                    "--window-position=-32000,-32000",  
                    "--window-size=1920,1080"           
                ])
            else:
                actual_headless = False
                browser_args.extend([
                    "--window-position=0,0",  
                    "--window-size=1920,1080"           
                ])
                
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=actual_headless, 
                args=browser_args
            )
            
             
            page = context.pages[0] if context.pages else context.new_page()
            try:
                 
                yield from execute_login(page, target_url, username, password)
                yield f"[{get_time()}] 等待系统重定向至课程主页..."
                page.wait_for_load_state("load", timeout=15000) 
                
                 
                yield f"[{get_time()}] 认证确认，正在接力执行视频拦截任务..."
                 
                
                yield from execute_video_task(
                    page, 
                    target_url, 
                    asr_worker, 
                    export_base_dir=config.get("export_base_dir", "./exports"),
                    stop_event=stop_event,   
                    need_subtitle=need_subtitle, 
                    need_ppt=need_ppt,
                    keep_media=keep_media,
                    target_date=st.session_state.selected_target_date
                )
                
            except Exception as e:
                yield f"[{get_time()}] 流程中断: {str(e)}"
            finally:
                yield f"[{get_time()}] 任务结束，清理浏览器..."
                time.sleep(2)
                context.close()
                
    except Exception as e:
        yield f"[{get_time()}] 浏览器引擎启动失败: {str(e)}"

def init_session_state(config):
    import threading
    if "stop_event" not in st.session_state:
        st.session_state.stop_event = threading.Event()
    if "is_running" not in st.session_state:
        st.session_state.is_running = False
    if "task_logs" not in st.session_state:          
        st.session_state.task_logs = ""
    if "fetched_dates" not in st.session_state:
        st.session_state.fetched_dates = []
    if "selected_target_date" not in st.session_state:
        st.session_state.selected_target_date = "自动获取最新"
    if "ai_summary_cache" not in st.session_state:
        st.session_state.ai_summary_cache = ""
    default_settings = {
        "headless_mode": config.get("headless_mode", False),
        "need_subtitle": config.get("need_subtitle", True),
        "need_ppt": config.get("need_ppt", False),
        "keep_media": config.get("keep_media", False),
        "asr_engine": config.get("asr_engine", "本地模型 (Faster-Whisper)"),
        "llm_engine": config.get("llm_engine", "DeepSeek (api.deepseek.com)"),
        "target_url": config.get("target_url", "https://cvs.seu.edu.cn"),
        "export_base_dir": config.get("export_base_dir", "./exports")
    }
    
     
    for key, default_val in default_settings.items():
        if key not in st.session_state:
            st.session_state[key] = default_val



 
config = load_config()

st.set_page_config(layout="wide", page_title="CVStream")

def main():
    init_session_state(config)
    kill_orphaned_browsers()
    
     
    st.markdown("""
    <style>
    /* 全局字体与纯净背景 */
    html, body, [class*="css"] {
        font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        background-color: #FFFFFF !important;
    }
    
    /* 侧边栏：取消右侧死板的分割线，让界面融为一体 */
    [data-testid="stSidebar"] {
        background-color: #FAFAFA !important;
        border-right: none !important; 
    }
    
    /* 按钮：去掉所有沉重的背景，回归线条与文字 */
    .stButton > button {
        border: 1px solid #E5E5E5 !important;
        background-color: transparent !important;
        color: #333333 !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        border-color: #000000 !important;
        color: #000000 !important;
        background-color: #F9F9F9 !important;
    }
    
    /* 核心主按钮（如运行）：纯黑底白字，极致聚焦 */
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: #111111 !important;
        color: white !important;
        border: none !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background-color: #000000 !important;
    }
    
    /* 输入框：底部单线设计，呼吸感拉满 */
    .stTextInput input, .stSelectbox div[data-baseweb="select"] {
        border: none !important;
        border-bottom: 1px solid #EAEAEA !important;
        border-radius: 0px !important;
        background-color: transparent !important;
        box-shadow: none !important;
    }
    .stTextInput input:focus, .stSelectbox div[data-baseweb="select"]:focus-within {
        border-bottom: 1px solid #111111 !important;
    }
    
    /* 取消各种原生卡片的边框 */
    div[data-testid="stVerticalBlock"] > div[style*="border: 1px solid"] {
        border: none !important;
        background-color: #FCFCFC !important;
        border-radius: 12px !important;
        padding: 20px !important;
        box-shadow: 0 2px 10px rgba(0,0,0,0.02) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    with st.sidebar:
         
        st.markdown("<div style='padding: 30px 0 20px 15px; font-size: 18px; font-weight: 400; letter-spacing: 3px; color: #111;'>CVSTREAM</div>", unsafe_allow_html=True)
        
         
        selected = option_menu(
            menu_title=None,
            options=["任务中心", "参数配置"],  
            icons=["", ""],  
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "nav-link": {
                    "font-size": "14px", 
                    "text-align": "left", 
                    "margin": "4px 15px", 
                    "padding": "10px 15px",
                    "color": "#999999",
                    "border-radius": "8px",
                    "background-color": "transparent"
                },
                "nav-link-selected": {
                    "color": "#111111",           
                    "font-weight": "600",
                    "background-color": "#F0F0F0", 
                    "border": "none"              
                },
            }
        )
        st.write("") 

        
        st.markdown("<div style='font-size: 14px; font-weight: 600; color: #111; margin-top: 25px; margin-bottom: 10px;'>系统加速</div>", unsafe_allow_html=True)
        
        if os.path.exists("R:\\"):
            
            st.markdown("""
                <div style='font-size: 13px; color: #2C7A7B; background-color: #F0FFF4; 
                            padding: 12px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #C6F6D5;'>
                    <b>内存盘 (R:) 已就绪</b><br>
                    <span style='font-size: 12px; opacity: 0.8;'>2GB 虚拟空间正处于活跃状态</span>
                </div>
            """, unsafe_allow_html=True)
            
            if st.button("释放并卸载虚拟盘", type="secondary", use_container_width=True):
                success, msg = remove_ramdisk("R:")
                if success:
                    with st.spinner("正在安全注销资源..."):
                        for _ in range(15):
                            if not os.path.exists("R:\\"): break
                            time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)
        else:
            
            st.markdown("""
                <div style='font-size: 14px; color: #666; background-color: #F7F7F7; 
                            padding: 12px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #EFEFEF;'>
                    <b>内存加速未开启</b><br>
                    <span style='font-size: 13px; opacity: 0.8;'>临时数据将通过物理硬盘读写，建议开启以延长 SSD 寿命。</span>
                </div>
            """, unsafe_allow_html=True)
            
            if st.button("一键开启内存盘 (2GB)", type="secondary", use_container_width=True):
                success, msg = setup_ramdisk("R:", "2G")
                if success:
                    with st.spinner("请在弹出的系统窗口点击'是'..."):
                        for _ in range(15):
                            if os.path.exists("R:\\"): break
                            time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)
        
        st.markdown("<div style='font-size: 14px; font-weight: 600; color: #111; margin-top: 20px; margin-bottom: 10px;'>输出目录</div>", unsafe_allow_html=True)
        current_export_dir = config.get("export_base_dir", "./exports")
        
       
        st.markdown(f"""
            <div style='font-size: 14px; color: #555; background-color: #F7F7F7; 
                        padding: 10px 12px; border-radius: 6px; margin-bottom: 15px; 
                        word-break: break-all; border: 1px solid #EFEFEF; font-family: monospace;'>
                {current_export_dir}
            </div>
        """, unsafe_allow_html=True)
        
        
        if st.button("更改保存位置", type="secondary", use_container_width=True):
            new_dir = select_folder()
            if new_dir:  
                from pathlib import Path
                
                normalized_dir = str(Path(new_dir))
                save_config({"export_base_dir": normalized_dir})
                st.rerun()


        st.write("")
        st.write("") 
        
        headless_mode = st.toggle(
            "开启无头模式", 
            key="headless_mode",
            on_change=sync_state_to_config, args=("headless_mode",)
        )
        st.divider()
        st.write("当前版本: v1.0.0")

    
    if selected == "参数配置":
        st.markdown("<h2 style='font-weight: 300; letter-spacing: -0.5px; margin-bottom: 20px;'>参数配置</h2>", unsafe_allow_html=True)
        with st.container(border=True):
            col_desc, col_input = st.columns([0.4, 0.6], gap="large")
            with col_desc:
                st.subheader("身份验证")
                st.markdown("请在此输入您的平台登录凭证。\n- **数据加密保存在本地**。")
                
                
                st.info("**首次使用必读**\n\n新用户或密码修改后，请务必点击右侧的【初始化授权环境】按钮，人工处理一次验证码，打通安全信道。")
                
            with col_input:
                u_input = st.text_input("用户名", value=config["username"], placeholder="请输入用户名")
                p_input = st.text_input("密码", value=config["password"], type="password", placeholder="请输入密码")
                
                st.caption(" 数据加密保存在本地 `config.json` 文件中。")
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("保存配置", use_container_width=True):
                        save_config({"username": u_input, "password": p_input})
                        st.success("配置已成功保存到本地！")
                
                
                with col_btn2:
                    if st.button("初始化授权环境 ", type="primary", use_container_width=True):
                        if not u_input or not p_input:
                            st.error("请先输入账号密码！")
                        else:
                            with st.status("正在唤起环境...", expanded=True) as status:
                                for msg in run_manual_init_login(config["target_url"], u_input, p_input):
                                    st.write(msg)
                                status.update(label="初始化流程结束", state="complete")

    elif selected == "任务中心": 
        
        st.markdown("<h1 style='font-weight: 300; letter-spacing: -1px; margin-bottom: 30px; margin-top: -20px;'>任务中心</h1>", unsafe_allow_html=True)
        
        
        opt_col1, opt_col2, opt_col3 = st.columns(3) 
        with opt_col1:
            need_subtitle = st.checkbox("获取字幕", key="need_subtitle", on_change=sync_state_to_config, args=("need_subtitle",))
        with opt_col2:
            need_ppt = st.checkbox("提取 PPT 图像 ", key="need_ppt", on_change=sync_state_to_config, args=("need_ppt",))
        with opt_col3:
            keep_media = st.checkbox("保存音视频原件", key="keep_media", on_change=sync_state_to_config, args=("keep_media",))
        
        st.write("")
        st.write("")  

        history_dict = config.get("history_urls", {"默认门户": "https://cvs.seu.edu.cn"})
        display_options = ["+ 新增地址..."] + list(history_dict.keys())
        
        last_label = config.get("last_selected_label", "默认门户")
        default_index = display_options.index(last_label) if last_label in display_options else 0
        
        col_name, col_url, col_btn = st.columns([0.3, 0.5, 0.2], vertical_alignment="bottom")
        
        with col_name:
            def save_label_choice():
                save_config({"last_selected_label": st.session_state["select_task_label"]})
                 
                st.session_state.fetched_dates = []
                st.session_state.selected_target_date = "自动获取最新"
                
            selected_label = st.selectbox(
                "选择任务/课程", 
                options=display_options,
                index=default_index,
                key="select_task_label",
                on_change=save_label_choice
            )

        with col_url:
            if selected_label == "+ 新增地址...":
                initial_url = ""
            else:
                initial_url = history_dict.get(selected_label, "")
            
            target_url = st.text_input(
                "目标网址", 
                value=initial_url, 
                key=f"url_input_{selected_label}" 
            )

        with col_btn:
            
            if not st.session_state.is_running:
                if st.button("▶ 运行", use_container_width=True, type="primary"):
                    st.session_state.stop_event.clear()
                    st.session_state.is_running = True
                    st.rerun()
            else:
                if st.button("⏹ 停止",use_container_width=True, type="secondary"):
                    st.session_state.stop_event.set()
                    if "asr_worker" in st.session_state:
                        st.session_state.asr_worker.abort()
                    with st.spinner("正在安全关闭浏览器及清理底层进程..."):
                        time.sleep(1) 
                        kill_orphaned_browsers() 
                    st.session_state.is_running = False
                    st.rerun()
                            
            run_btn = st.session_state.is_running

         
        date_col1, date_col2 = st.columns([0.5, 0.5], vertical_alignment="bottom")
        
        with date_col1:
            date_options = ["自动获取最新"] + st.session_state.fetched_dates
            
             
            current_index = 0
            if st.session_state.selected_target_date in date_options:
                current_index = date_options.index(st.session_state.selected_target_date)
                
            selected_date = st.selectbox(
                "指定抓取批次 (日期)", 
                options=date_options, 
                index=current_index,
                key="date_selector",
                help="默认抓取最新一节。若需抓取历史课程，请先点击右侧刷新按钮。"
            )
            st.session_state.selected_target_date = selected_date
            
        with date_col2:
            trigger_refresh = st.button("刷新日期列表", use_container_width=True)
        
        
         
        is_adding_new = (selected_label == "+ 新增地址...")

        with st.expander("书签管理 (增加/删除网址)",expanded=is_adding_new):
            new_alias = st.text_input("为当前网址起个名 (如: 高数A)", placeholder="输入名称")
            if is_adding_new:
                st.markdown("请在上方输入网址，在此处起个名字，然后点击下方保存。")
            c1, c2 = st.columns(2)
            if c1.button("保存到收藏夹", use_container_width=True):
                if new_alias and target_url:
                    history_dict[new_alias] = target_url
                    save_config({"history_urls": history_dict})
                    st.success(f"已保存: {new_alias}")
                    st.rerun()
            if c2.button("删除当前选择", use_container_width=True):
                if selected_label in history_dict:
                    del history_dict[selected_label]
                    save_config({"history_urls": history_dict})
                    st.rerun()
        

        if trigger_refresh:
            if not target_url or not target_url.startswith("http"):
                st.error("请先在上方输入正确的目标网址。")
            else:
                 
                with st.status("正在静默探测课程数据...", expanded=True) as status:
                    dates_result = []
                     
                    for msg in run_fetch_dates_pipeline(target_url, config["username"], config["password"], headless_mode):
                        if isinstance(msg, list):
                            dates_result = msg  
                        else:
                             
                            st.write(msg)
                    
                    if dates_result:
                        status.update(label="日期列表获取成功！", state="complete")
                        st.session_state.fetched_dates = dates_result
                        st.session_state.selected_target_date = "自动获取最新"
                         
                        if "date_selector" in st.session_state:
                            del st.session_state["date_selector"]
                        time.sleep(1)
                        st.rerun()
                    else:
                        status.update(label="探测失败，请检查登录状态", state="error")
        
        st.write("")
        st.markdown("### 运行状态")
        show_system_status_cards(target_url)   

        st.write("")
        
        st.markdown("### 模型调度配置")
        
        with st.container(border=True):
             
             
             
            st.markdown("##### 语音转文字 (ASR)")
            
            BASE_ASR_ENDPOINTS = {
                "阿里 Paraformer (DashScope)": "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
                "本地模型 (Faster-Whisper)": "LOCAL_PATH"
            }
            
            custom_asrs = config.get("custom_asr_endpoints", {})
            custom_asrs = {k: v for k, v in custom_asrs.items() if k not in BASE_ASR_ENDPOINTS}
            ALL_ASR_ENDPOINTS = {**BASE_ASR_ENDPOINTS, **custom_asrs}
            
            ADD_NEW_ASR = "+ 添加自定义 ASR 端点/路径..."
            asr_options = [ADD_NEW_ASR] + list(ALL_ASR_ENDPOINTS.keys())
            
             
            current_asr = st.session_state.get("asr_engine")
            if current_asr not in asr_options:
                current_asr = asr_options[1]   
                st.session_state.asr_engine = current_asr

            def on_asr_change():
                new_val = st.session_state["ui_asr_selectbox"]
                st.session_state.asr_engine = new_val
                save_config({"asr_engine": new_val})

            selected_asr = st.selectbox(
                "选择语音识别模型",
                options=asr_options, 
                index=asr_options.index(current_asr),  
                key="ui_asr_selectbox",                
                on_change=on_asr_change
            )
            
            is_adding_new_asr = (selected_asr == ADD_NEW_ASR)
            
            if is_adding_new_asr:
                add_c1, add_c2, add_c3 = st.columns([0.35, 0.45, 0.2], vertical_alignment="bottom")
                with add_c1:
                    new_asr_name = st.text_input("端点名称", placeholder="例如：我的私有 Whisper", key="new_asr_name")
                with add_c2:
                    new_asr_url = st.text_input("API URL 或 本地路径", placeholder="wss://... 或 ./models/...", key="new_asr_url")
                with add_c3:
                    if st.button("保存并添加", type="primary", use_container_width=True, key="btn_add_custom_asr"):
                        if new_asr_name and new_asr_url:
                            custom_asrs[new_asr_name] = new_asr_url
                            save_config({"custom_asr_endpoints": custom_asrs, "asr_engine": new_asr_name})
                            st.session_state.asr_engine = new_asr_name
                            st.rerun()
            else:
                is_custom_asr = selected_asr in custom_asrs
                is_local_asr = (selected_asr == "本地模型 (Faster-Whisper)")
                
                if is_custom_asr:
                    c_url, c_key, c_btn1, c_btn2 = st.columns([0.3, 0.3, 0.2, 0.2], vertical_alignment="bottom")
                else:
                    c_url, c_key, c_btn1 = st.columns([0.4, 0.4, 0.2], vertical_alignment="bottom")
                
                with c_url:
                    st.text_input("ASR 路径/URL", value=ALL_ASR_ENDPOINTS.get(selected_asr, ""), disabled=True, key="asr_url_display")
                
                with c_key:
                    saved_asr_key = config.get("asr_api_key", "")
                    saved_model_path = config.get("asr_model_path", "")
                    
                    is_locked = (not is_local_asr and bool(saved_asr_key)) or (is_local_asr and bool(saved_model_path))
                    
                    if is_locked:
                        display_val = f"已就绪: {os.path.basename(saved_model_path)}" if is_local_asr else "*" * 20
                        st.text_input("状态验证", value=display_val, disabled=True, key="asr_key_locked")
                    else:
                        if is_local_asr:
                            st.text_input("模型目录", value="等待选择...", disabled=True, key="asr_path_pending")
                        else:
                            asr_key_input = st.text_input("API 密钥 (Key)", type="password", placeholder="请输入对应 Key...", key="asr_key_input")
                            
                with c_btn1:
                    if is_locked:
                        if st.button("清空配置 (修改)", use_container_width=True, key="btn_reset_asr"):
                            save_config({"asr_api_key": "", "asr_model_path": ""})
                            st.rerun()
                    else:
                        if is_local_asr:
                            if st.button("浏览选择文件夹", use_container_width=True, type="primary", key="btn_browse_asr"):
                                path = select_folder()
                                if path:
                                    save_config({"asr_model_path": path})
                                    st.rerun()
                        else:
                            if st.button("保存密钥", use_container_width=True, type="primary", key="btn_lock_asr"):
                                if asr_key_input:
                                    save_config({"asr_api_key": asr_key_input})
                                    st.rerun()
                                    
                if is_custom_asr:
                    with c_btn2:
                        if st.button("删除此端点", use_container_width=True, key="btn_del_custom_asr"):
                            del custom_asrs[selected_asr]
                            fallback_asr = list(BASE_ASR_ENDPOINTS.keys())[0]
                            save_config({"custom_asr_endpoints": custom_asrs, "asr_engine": fallback_asr})
                            st.session_state.asr_engine = fallback_asr
                            st.rerun()

            st.divider()

             
             
             
            st.markdown("##### 逻辑推理 (LLM)")
            
            BASE_LLM_ENDPOINTS = {
                "DeepSeek (api.deepseek.com)": "https://api.deepseek.com/v1",
                "豆包 (ark.cn-beijing.volces.com)": "https://ark.cn-beijing.volces.com/api/v3",
                "智谱清言 (open.bigmodel.cn)": "https://open.bigmodel.cn/api/paas/v4",
                "Kimi (api.moonshot.cn)": "https://api.moonshot.cn/v1",
                "MiniMax (api.minimax.chat)": "https://api.minimax.chat/v1",
                "通义千问 (DashScope)": "https://dashscope.aliyuncs.com/compatible-mode/v1"
            }
            
            custom_llms = config.get("custom_llm_endpoints", {})
            custom_llms = {k: v for k, v in custom_llms.items() if k not in BASE_LLM_ENDPOINTS}
            ALL_LLM_ENDPOINTS = {**BASE_LLM_ENDPOINTS, **custom_llms}
            
            ADD_NEW_LLM = "+ 添加自定义推理端点..."
            llm_options = [ADD_NEW_LLM] + list(ALL_LLM_ENDPOINTS.keys())

             
            current_llm = st.session_state.get("llm_engine")
            if current_llm not in llm_options:
                current_llm = llm_options[1]   
                st.session_state.llm_engine = current_llm

            def on_llm_change():
                new_val = st.session_state["ui_llm_selectbox"]
                st.session_state.llm_engine = new_val
                save_config({"llm_engine": new_val})

            selected_llm = st.selectbox(
                "选择推理模型端点", 
                options=llm_options, 
                index=llm_options.index(current_llm),  
                key="ui_llm_selectbox",                
                on_change=on_llm_change
            )

            is_adding_new_llm = (selected_llm == ADD_NEW_LLM)

            if is_adding_new_llm:
                c1, c2, c3 = st.columns([0.35, 0.45, 0.2], vertical_alignment="bottom")
                with c1: 
                    n_name = st.text_input("端点名称", placeholder="例如：我的私有大模型", key="n_llm_n")
                with c2: 
                    n_url = st.text_input("Base URL", placeholder="https://...", key="n_llm_u")
                with c3:
                    if st.button("保存并添加", type="primary", use_container_width=True, key="save_llm"):
                        if n_name and n_url:
                            custom_llms[n_name] = n_url
                            save_config({"custom_llm_endpoints": custom_llms, "llm_engine": n_name})
                            st.session_state.llm_engine = n_name
                            st.rerun()
            else:
                is_cust_llm = selected_llm in custom_llms
                cols = st.columns([0.3, 0.3, 0.2, 0.2] if is_cust_llm else [0.4, 0.4, 0.2], vertical_alignment="bottom")
                
                with cols[0]: 
                    st.text_input("Base URL", value=ALL_LLM_ENDPOINTS[selected_llm], disabled=True, key="llm_url_v")
                
                saved_llm_key = config.get("api_key", "")
                is_llm_locked = bool(saved_llm_key)
                
                with cols[1]: 
                    if is_llm_locked:
                        st.text_input("API密钥", value="*"*20, disabled=True, key="llm_key_locked")
                    else:
                        llm_key_input = st.text_input("API 密钥 (Key)", type="password", placeholder="请输入对应 Key...", key="llm_key_input")
                
                with cols[2]:
                    if is_llm_locked:
                        if st.button("清空配置 (修改)", use_container_width=True, key="edit_llm"):
                            save_config({"api_key": ""}) 
                            st.rerun()
                    else:
                        if st.button("保存密钥", use_container_width=True, type="primary", key="save_llm_key"):
                            if llm_key_input:
                                save_config({"api_key": llm_key_input})
                                st.rerun()
                        
                if is_cust_llm:
                    with cols[3]:
                        if st.button("删除此端点", use_container_width=True, key="del_llm"):
                            del custom_llms[selected_llm]
                            fallback_llm = list(BASE_LLM_ENDPOINTS.keys())[0]
                            save_config({"custom_llm_endpoints": custom_llms, "llm_engine": fallback_llm})
                            st.session_state.llm_engine = fallback_llm
                            st.rerun()
                        
                

            st.markdown("---")  
            
            st.markdown("##### 模型版本管理")

            
            current_asr_url = ALL_ASR_ENDPOINTS.get(selected_asr, "").lower()
            recommended_asr_models = ["paraformer-realtime-v2", "paraformer-realtime-v1", "paraformer-v1", "whisper-1"]
            
            
            asr_model_map = {
                "aliyuncs": ["paraformer-realtime-v2", "paraformer-realtime-v1", "paraformer-v1", "paraformer-8k-v1"]
            }
            
            for key_str, models in asr_model_map.items():
                if key_str in current_asr_url:
                    recommended_asr_models = models.copy()
                    break
                    
            custom_asr_models_dict = config.get("custom_asr_models", {})
            saved_custom_asr_models = custom_asr_models_dict.get(selected_asr, [])
            
            all_asr_options = []
            for m in saved_custom_asr_models + recommended_asr_models:
                if m not in all_asr_options:
                    all_asr_options.append(m)
            
            all_asr_options.append("+ 添加自定义模型版本...")
                    
            dynamic_asr_key = f"asr_version_{selected_asr}"
            
            # 独立读取 ASR 版本
            current_saved_asr_version = config.get("asr_model_version", "")
            if current_saved_asr_version in all_asr_options:
                asr_default_idx = all_asr_options.index(current_saved_asr_version)
            else:
                asr_default_idx = 0
                
            def on_asr_version_change():
                save_config({"asr_model_version": st.session_state[dynamic_asr_key]})

            selected_asr_version = st.selectbox(
                "指定 ASR 模型版本", 
                options=all_asr_options, 
                index=asr_default_idx,
                key=dynamic_asr_key, 
                on_change=on_asr_version_change,
                help="指定调用的具体语音识别模型。⚠️ 提示：云端 ASR API 传输和排队时间较长（大文件可能需数分钟），请耐心等待进程完成。"
            )

            # 同步 ASR 默认值
            if current_saved_asr_version != selected_asr_version and selected_asr_version != "+ 添加自定义模型版本...":
                save_config({"asr_model_version": selected_asr_version})

            # ASR 自定义与删除逻辑
            if selected_asr_version == "+ 添加自定义模型版本...":
                add_c1, add_c2 = st.columns([0.8, 0.2], vertical_alignment="bottom")
                with add_c1:
                    new_asr_model_name = st.text_input(
                        "输入 ASR 模型名称", 
                        placeholder="例如: paraformer-realtime-v2",
                        key=f"new_asr_model_input_{selected_asr}",
                        label_visibility="collapsed"
                    )
                with add_c2:
                    if st.button("保存至列表", key=f"save_asr_model_btn_{selected_asr}", use_container_width=True):
                        if new_asr_model_name and new_asr_model_name not in saved_custom_asr_models:
                            saved_custom_asr_models.append(new_asr_model_name)
                            custom_asr_models_dict[selected_asr] = saved_custom_asr_models
                            save_config({"custom_asr_models": custom_asr_models_dict, "asr_model_version": new_asr_model_name})
                            st.rerun()
            elif selected_asr_version in saved_custom_asr_models:
                if st.button("删除此自定义 ASR 版本", key=f"del_asr_model_btn_{selected_asr}", use_container_width=False):
                    saved_custom_asr_models.remove(selected_asr_version)
                    custom_asr_models_dict[selected_asr] = saved_custom_asr_models
                    save_config({"custom_asr_models": custom_asr_models_dict})
                    st.rerun()

            st.write("") # 增加上下间距


            
            current_llm_url = ALL_LLM_ENDPOINTS.get(selected_llm, "").lower()
            recommended_llm_models = ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"]
            
            llm_model_map = {
                "deepseek": ["deepseek-chat", "deepseek-reasoner"],
                "aliyuncs": ["qwen-plus", "qwen-max", "qwen-turbo"],
                "volces": ["ep-此处替换为你的接入点ID( 自定义模型版本)"],
                "bigmodel": ["glm-4.7", "glm-4-plus"],
                "moonshot": ["moonshot-v1-8k", "moonshot-v1-32k"],
                "minimax": ["abab6.5s-chat", "abab6.5-chat"]
            }
            
            for key_str, models in llm_model_map.items():
                if key_str in current_llm_url:
                    recommended_llm_models = models.copy()
                    break
                    
            custom_llm_models_dict = config.get("custom_models", {})
            saved_custom_llm_models = custom_llm_models_dict.get(selected_llm, [])
            
            all_llm_options = []
            for m in saved_custom_llm_models + recommended_llm_models:
                if m not in all_llm_options:
                    all_llm_options.append(m)
            
            all_llm_options.append("+ 添加自定义模型版本...")
                    
            dynamic_llm_key = f"ai_version_{selected_llm}"
            
            
            current_saved_llm_version = config.get("llm_model_version", "")
            if current_saved_llm_version in all_llm_options:
                llm_default_idx = all_llm_options.index(current_saved_llm_version)
            else:
                llm_default_idx = 0
                
            def on_llm_version_change():
                save_config({"llm_model_version": st.session_state[dynamic_llm_key]})

            selected_llm_version = st.selectbox(
                "指定 AI 模型版本", 
                options=all_llm_options, 
                index=llm_default_idx,
                key=dynamic_llm_key, 
                on_change=on_llm_version_change,
                help="手动指定 API 调用时的 model 参数"
            )

            
            if current_saved_llm_version != selected_llm_version and selected_llm_version != "+ 添加自定义模型版本...":
                save_config({"llm_model_version": selected_llm_version})

            
            if selected_llm_version == "+ 添加自定义模型版本...":
                add_col1, add_col2 = st.columns([0.8, 0.2], vertical_alignment="bottom")
                with add_col1:
                    new_llm_model_name = st.text_input(
                        "输入模型/接入点名称", 
                        placeholder="例如: ep-12345678-abcde",
                        key=f"new_llm_model_input_{selected_llm}",
                        label_visibility="collapsed"
                    )
                with add_col2:
                    if st.button("保存至列表", key=f"save_llm_model_btn_{selected_llm}", use_container_width=True):
                        if new_llm_model_name and new_llm_model_name not in saved_custom_llm_models:
                            saved_custom_llm_models.append(new_llm_model_name)
                            custom_llm_models_dict[selected_llm] = saved_custom_llm_models
                            save_config({"custom_models": custom_llm_models_dict, "llm_model_version": new_llm_model_name})
                            st.rerun()
            elif selected_llm_version in saved_custom_llm_models:
                if st.button("删除此自定义版本", key=f"del_llm_model_btn_{selected_llm}", use_container_width=False):
                    saved_custom_llm_models.remove(selected_llm_version)
                    custom_llm_models_dict[selected_llm] = saved_custom_llm_models
                    save_config({"custom_models": custom_llm_models_dict})
                    st.rerun()

            st.write("") # 增加底部间距


            
            from pathlib import Path
            
            base_dir = Path(config.get("export_base_dir", "./exports"))
            subtitle_dir = base_dir / "subtitle"
            
            available_courses = []
            if subtitle_dir.exists():
                available_courses = [d.name for d in subtitle_dir.iterdir() if d.is_dir()]
            
            if not available_courses:
                st.info("本地暂无字幕数据，请先运行抓取任务。")
            else:
                sel_col1, sel_col2, sel_col3 = st.columns([0.35, 0.35, 0.3], vertical_alignment="bottom")
                with sel_col1:
                    target_course = st.selectbox("选择要总结的课程", options=available_courses, key="sum_course_sel")
                with sel_col2:
                    course_dir = subtitle_dir / target_course
                    available_dates = [d.name for d in course_dir.iterdir() if d.is_dir()]
                    target_date = st.selectbox("选择课程批次", options=available_dates, key="sum_date_sel")
                with sel_col3:
                    start_sum = st.button("生成今日 AI 知识提炼", use_container_width=True, type="primary")

                if start_sum:
                    if selected_llm_version == "+ 添加自定义模型版本...":
                        st.error("请先完成自定义模型的输入并点击保存。")
                    else:
                        try:
                            from ai_summary import AISummarizer
                            
                            temp_config = config.copy()
                            temp_config["llm_engine"] = selected_llm
                            
                            summarizer = AISummarizer(temp_config)
                            summarizer.model_name = selected_llm_version 
                            
                            with st.container(border=True):
                                st.markdown(f"#### 正在生成: {target_course} ({target_date})")
                                 
                                output_area = st.empty() 
                                
                                stream_gen = summarizer.generate_daily_summary(
                                    config.get("export_base_dir", "./exports"), 
                                    target_course, 
                                    target_date
                                )
                                
                                full_content = st.write_stream(stream_gen)
                                st.session_state.ai_summary_cache = full_content

                                export_base_dir = config.get("export_base_dir", "./exports")
                                knowledge_dir = Path(export_base_dir) / "knowledge" / target_course
                                knowledge_dir.mkdir(parents=True, exist_ok=True)
                                
                                output_file = knowledge_dir / f"{target_date}_Summary.md"
                                with open(output_file, "w", encoding="utf-8") as f:
                                    f.write(f"# 核心知识提炼: {target_course} ({target_date})\n\n")
                                    f.write(full_content)
                                    
                                st.success(f"总结已归档至: {output_file.name}")
                                
                        except Exception as e:
                            err_msg = str(e)
                            if "429" in err_msg:
                                st.error("总结失败：您的 AI 账户已达到请求速率限制。请等待 1 分钟后再试，或更换其他模型端点。")
                            else:
                                st.error(f"总结失败: {err_msg}")

                elif st.session_state.ai_summary_cache:
                    st.divider()
                    with st.chat_message("assistant"):
                        st.markdown(st.session_state.ai_summary_cache)

        
        st.markdown(
            """
            <div style="
                text-align: right; 
                font-size: 12px; 
                color: #999; 
                margin-top: -15px; 
                margin-right: 5px;
                margin-bottom: 20px;
            ">
                提示：若 API 额度耗尽，可以考虑手动投喂 
                <a href="https://www.doubao.com/chat/" target="_blank" style="color: #666; text-decoration: none;">豆包</a>
            </div>
            """, 
            unsafe_allow_html=True
        )
        st.write("")
        st.markdown("### 运行结果")
        
        with st.container(border=True):
            status_text = st.empty()
            log_placeholder = st.empty()
            
            if not run_btn:
                status_text.write("系统就绪，等待任务启动...")
                 
                if st.session_state.get("task_logs"):
                    log_placeholder.code(st.session_state.task_logs, language="bash")
                else:
                    log_placeholder.code("\n" * 10, language="bash")

             

            if run_btn:
                if not target_url or not target_url.startswith("http"):
                    st.error("拦截操作：目标网址为空或格式错误！")
                else:
                    if st.session_state.asr_engine == "本地模型 (Faster-Whisper)":
                        current_model_path = config.get("asr_model_path", "")
                        if not current_model_path or not os.path.exists(current_model_path):
                            st.error("拦截操作：本地 ASR 模型目录不存在，请先在上方配置模型路径。")
                            st.stop()
                    else:
                        # 🌟 修复 1：云端模型校验，增加 API Key 的前置拦截
                        current_asr_version = config.get("asr_model_version", "")
                        if not current_asr_version or current_asr_version == "+ 添加自定义模型版本...":
                            st.error("拦截操作：云端 ASR 引擎未指定具体的模型版本！请先在上方选择。")
                            st.stop()
                        if not config.get("asr_api_key", "").strip():
                            st.error("拦截操作：未配置云端 ASR 的 API 密钥 (Key)！请在上方填写并保存。")
                            st.stop()
                        # 🌟 修复 2：防止“挂羊头卖狗肉”，当前只允许走阿里的引擎名
                        if "阿里" not in st.session_state.asr_engine and "aliyuncs" not in st.session_state.asr_engine.lower():
                            st.error("拦截操作：当前云端底层代码 (asr_cloud.py) 仅支持阿里云 DashScope 接口。请选择阿里系端点！")
                            st.stop()

                    with st.status("正在执行任务...", expanded=True) as status:
                        log_container = st.empty()
                        progress_bar = st.empty()
                        
                        st.session_state.task_logs = "" 
                        
                        # 🌟 修复 3：彻底解决 Worker 缓存不更新 Bug。每次运行都强制注入最新的 config
                        current_ui_asr = st.session_state.get("asr_engine")
                        if current_ui_asr == "本地模型 (Faster-Whisper)":
                            st.session_state.asr_worker = LocalASRWorker(
                                model_path=config.get("asr_model_path", "./models/faster-whisper-tiny"),
                                export_base_dir=config.get("export_base_dir", "./exports")
                            )
                        else:
                            from asr_cloud import CloudASRWorker
                            st.session_state.asr_worker = CloudASRWorker(
                                config=config,  # 传入刚从 UI 保存好的最新 config
                                export_base_dir=config.get("export_base_dir", "./exports")
                            )
                            
                        current_worker = st.session_state.get("asr_worker")

                        

                        for log_line in run_pipeline(
                            target_url, 
                            config["username"], 
                            config["password"], 
                            headless=headless_mode,
                            asr_worker=current_worker,
                            stop_event=st.session_state.stop_event,
                            need_subtitle=need_subtitle,  
                            need_ppt=need_ppt,           
                            keep_media=keep_media,
                            target_date=st.session_state.selected_target_date     
                        ):
                            if log_line.startswith("[ASR_PROGRESS] "):
                                 
                                try:
                                    p_data = json.loads(log_line.replace("[ASR_PROGRESS] ", ""))
                                    prog_val = p_data.get("progress", 0.0)
                                    text_preview = p_data.get("text", "")[:20]
                                    progress_bar.progress(prog_val, text=f"ASR 转写中: {int(prog_val * 100)}% | {text_preview}...")
                                    if p_data.get("done"): progress_bar.empty()
                                except: pass
                            else:
                                 
                                st.session_state.task_logs += log_line + "\n"
                                 
                                log_container.code(st.session_state.task_logs, language="bash")

                         
                        st.session_state.is_running = False
                        status.update(label="任务完成/已终止", state="complete")
                        time.sleep(1)  
                        st.rerun()
        st.divider()
        st.caption("CVStream © 2026 - 保留所有权利")

if __name__ == "__main__":
    main()