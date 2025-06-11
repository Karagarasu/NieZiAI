import tkinter as tk
from tkinter import Toplevel
import random
import threading
import pygame
import win32gui
import win32con
import pyautogui
from PIL import Image, ImageTk
import time
import os
import sys
import ctypes
import ctypes.wintypes as wintypes

# --- 配置区 ---
TOTAL_WINDOWS = 35  # 程序自身创建的窗口总数
WINDOW_CREATION_DELAY_MS = 400  # 创建窗口之间的延迟（毫秒）
BOUNCE_SPEED_RANGE = [-3, -2, 2, 3]  # 窗口弹跳速度（像素/步）范围
SOUND_FILE = "mymp3.mp3"  # 要播放的音频文件名，确保此文件存在于程序运行目录或images子目录外
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')  # 支持的图片文件扩展名
EXTERNAL_WINDOW_ENUM_INTERVAL = 1.0  # 秒 - 扫描外部窗口的频率
JAVA_WINDOW_DEMOTE_INTERVAL = 0.1  # 秒 - 降低Java窗口的频率（更激进！）
FORCE_TOPMOST_INTERVAL = 500  # 毫秒 - 自身窗口强制置顶的频率
# --- 配置区结束 ---

# 初始化屏幕尺寸
screen_width, screen_height = pyautogui.size()

# 获取应用程序的根目录
APP_ROOT_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(
    os.path.abspath(__file__))

print(f"应用程序根目录: {APP_ROOT_DIR}")

# --- Windows API 常量定义 ---
# 窗口扩展样式
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000  # 防止窗口被激活

# SetWindowPos Flags
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

# LWA Flags (for SetLayeredWindowAttributes)
LWA_ALPHA = 0x00000002

# SystemParametersInfoW Flags
SPI_SETSCREENSAVEACTIVE = 0x0011  # 设置屏保状态

# SetThreadExecutionState Flags (防止系统休眠或显示器关闭)
ES_CONTINUOUS = 0x80000000
ES_DISPLAY_REQUIRED = 0x00000002

# 进程优先级常量
NORMAL_PRIORITY_CLASS = 0x00000020
IDLE_PRIORITY_CLASS = 0x00000040
HIGH_PRIORITY_CLASS = 0x00000080
REALTIME_PRIORITY_CLASS = 0x00000100
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000

# --- Pygame 音频初始化 ---
try:
    pygame.mixer.init()
    print("Pygame mixer 初始化成功。")
except Exception as e:
    print(f"Pygame mixer 初始化失败: {e}. 音频功能将不可用。")


# --- 提权函数 ---
def run_as_admin(command=None, wait=True):
    """
    Attempts to re-run the current script with administrator privileges on Windows.
    If 'command' is provided, it runs that command instead of the current script.
    'wait' specifies whether to wait for the elevated process to exit.
    """
    if sys.platform != 'win32':
        print("此提权功能仅支持Windows系统。")
        return False

    try:
        # Check if already running as administrator
        if ctypes.windll.shell32.IsUserAnAdmin():
            print("程序已具有管理员权限。")
            return True
        else:
            print("尝试以管理员权限重新启动程序...")
            # Re-run the script with admin privileges
            if command is None:
                # Get the path of the current script
                script_path = os.path.abspath(sys.argv[0])
                # Arguments to pass to the new process (excluding the script path itself)
                arguments = ' '.join(sys.argv[1:])

                # Determine the correct Python executable (python.exe or pythonw.exe)
                if sys.executable.endswith("pythonw.exe"):
                    file_exe = "pythonw.exe"
                else:
                    file_exe = "python.exe"

                # Construct the full command parameters
                param = f'"{script_path}" {arguments}'

                # ShellExecuteW takes 6 arguments: hwnd, lpVerb, lpFile, lpParameters, lpDirectory, nShowCmd
                process_info = ctypes.windll.shell32.ShellExecuteW(
                    None,  # hwnd
                    "runas",  # lpVerb: "runas" requests elevation
                    file_exe,  # lpFile: executable to run
                    param,  # lpParameters: arguments to the executable
                    os.getcwd(),  # lpDirectory: current working directory
                    1  # nShowCmd: SW_SHOWNORMAL
                )

                # ShellExecuteW returns a value > 32 on success.
                if process_info > 32:
                    if wait:
                        print("已启动新的管理员进程，当前非管理员进程即将退出。")
                        sys.exit(0)  # Exit the non-elevated process
                    else:
                        print("已启动新的管理员进程，当前非管理员进程继续运行 (但不等待)。")
                        return True
                else:
                    print(f"提权失败，错误代码: {process_info}")
                    return False

            else:  # If a specific command is provided (less common for self-elevation)
                process_info = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", command.split()[0], ' '.join(command.split()[1:]), os.getcwd(), 1
                )
                if process_info > 32:
                    if wait:
                        print("已启动新的管理员进程 (命令行)，当前进程即将退出。")
                        sys.exit(0)
                    else:
                        print("已启动新的管理员进程 (命令行)，当前进程继续运行 (但不等待)。")
                        return True
                else:
                    print(f"提权失败，错误代码: {process_info}")
                    return False

    except Exception as e:
        print(f"提权过程中发生错误: {e}")
        return False


# --- WindowManager 类定义 ---
class WindowManager:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # 隐藏主Tkinter窗口

        self.windows = []  # 存储自身创建的窗口信息
        self.moving_active = False  # 控制移动线程的启停
        self.creation_timer = None  # 窗口创建定时器
        self.force_topmost_timer = None  # 自身窗口强制置顶定时器
        self.external_window_timer = None  # 扫描外部窗口定时器
        self.java_window_timer = None  # 降低Java窗口定时器

        self.image_files = self._load_images()

        # --- 背景音乐：预加载并设置为循环播放 ---
        self.background_music_loaded = False
        sound_path = os.path.join(APP_ROOT_DIR, SOUND_FILE)
        if os.path.exists(sound_path):
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.music.load(sound_path)
                    self.background_music_loaded = True
                    print(f"背景音乐文件 '{SOUND_FILE}' 预加载成功。")
                else:
                    print("Pygame mixer 未初始化，无法预加载背景音乐。")
            except Exception as e:
                print(f"预加载背景音乐 '{SOUND_FILE}' 失败: {e}")
        else:
            print(f"警告: 背景音乐文件 '{SOUND_FILE}' 不存在于 '{APP_ROOT_DIR}'。将无法播放背景音乐。")
        # --- 背景音乐结束 ---

        self.external_moving_windows = {}  # 存储外部窗口的移动信息

        # 设置当前进程优先级
        self.set_current_process_priority(HIGH_PRIORITY_CLASS)  # 激进策略：自身程序高优先级

    def _load_images(self):
        """加载图片文件"""
        image_dir = os.path.join(APP_ROOT_DIR, "images")
        if not os.path.exists(image_dir):
            print(f"警告: 图像目录 '{image_dir}' 不存在。请创建该目录并放入图片文件。")
            return []

        images = []
        for filename in os.listdir(image_dir):
            if filename.lower().endswith(IMAGE_EXTENSIONS):
                try:
                    img_path = os.path.join(image_dir, filename)
                    img = Image.open(img_path)
                    # 调整图片大小以适应窗口，这里简单固定为100x100，你可以根据需要调整
                    img = img.resize((100, 100), Image.Resampling.LANCZOS)
                    images.append(ImageTk.PhotoImage(img))
                except Exception as e:
                    print(f"加载图片 '{filename}' 失败: {e}")
        if not images:
            print("警告: 未找到任何可用图片文件。")
        return images

    def _destroy_window(self, info):
        """销毁一个窗口并从列表中移除"""
        try:
            info['window'].destroy()
        except tk.TclError:
            pass  # 窗口可能已经被销毁
        if info in self.windows:
            self.windows.remove(info)
        print(f"窗口 HWND {info['hwnd']} 已销毁。")

    def set_strong_window_properties(self, hwnd):
        """
        设置窗口的激进属性：分层、置顶、透明点击、不激活。
        """
        try:
            # 获取当前扩展样式
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            # 添加 WS_EX_LAYERED, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE
            new_style = style | WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, new_style)

            # 设置分层窗口的透明度（0表示完全透明，255表示完全不透明）
            # 这里设置为255，表示不透明，但启用了分层窗口机制
            win32gui.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
            print(f"窗口 HWND {hwnd} 已设置激进属性。")
        except Exception as e:
            print(f"设置窗口 HWND {hwnd} 激进属性失败: {e}")

    def force_window_topmost(self):
        """
        强力将所有自身创建的窗口置顶，通过一系列操作确保Z-order。
        """
        for info in self.windows[:]:  # 遍历副本以防止修改时出错
            hwnd = info['hwnd']
            if win32gui.IsWindow(hwnd):
                try:
                    # 1. 先解除置顶 (尝试重置Z-order)
                    win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                    # 2. 立即置顶到所有非置顶窗口之上
                    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                    # 3. 最后再使用 HWND_TOP (在所有当前置顶窗口中，置于最上)
                    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                except Exception as e:
                    print(f"强力置顶窗口 HWND {hwnd} 失败: {e}")
                    # 窗口可能已失效，从列表中移除
                    if info in self.windows:
                        self.windows.remove(info)

    def periodic_force_topmost(self):
        """定时调用强力置顶函数"""
        if self.moving_active:
            self.force_window_topmost()
            self.force_topmost_timer = self.root.after(FORCE_TOPMOST_INTERVAL, self.periodic_force_topmost)

    def create_window(self):
        """创建一个新窗口"""
        if len(self.windows) >= TOTAL_WINDOWS or not self.moving_active:
            return

        if not self.image_files:
            print("没有可用的图片文件，无法创建窗口。")
            return

        img = random.choice(self.image_files)
        window = Toplevel(self.root)
        window.overrideredirect(True)  # 移除窗口边框和标题栏
        window.attributes('-topmost', True)  # Tkinter层面的置顶

        # 随机初始位置和速度
        x = random.randint(0, screen_width - img.width())
        y = random.randint(0, screen_height - img.height())
        speed_x = random.choice(BOUNCE_SPEED_RANGE)
        speed_y = random.choice(BOUNCE_SPEED_RANGE)

        window.geometry(f'{img.width()}x{img.height()}+{x}+{y}')
        label = tk.Label(window, image=img, bg='white')
        label.pack()

        # 获取窗口句柄并设置激进属性
        window.update_idletasks()  # 确保窗口已创建并获取句柄
        hwnd = win32gui.GetParent(window.winfo_id())  # 获取Toplevel窗口的父句柄

        self.set_strong_window_properties(hwnd)  # 设置激进属性

        self.windows.append({
            'window': window,
            'hwnd': hwnd,
            'x': x,
            'y': y,
            'speed_x': speed_x,
            'speed_y': speed_y,
            'width': img.width(),
            'height': img.height()
        })
        print(f"创建窗口 HWND {hwnd}，当前总数: {len(self.windows)}")
        # 注意：此处不再调用 _play_sound，因为背景音乐是独立循环播放的

        self.creation_timer = self.root.after(WINDOW_CREATION_DELAY_MS, self.create_window)

    def _is_our_window(self, hwnd):
        """判断是否是自己创建的窗口"""
        return any(info['hwnd'] == hwnd for info in self.windows)

    def _enum_windows_proc(self, hwnd, extra):
        """枚举窗口回调函数"""
        if not win32gui.IsWindowVisible(hwnd):
            return True  # 跳过不可见窗口

        if self._is_our_window(hwnd):
            return True  # 跳过自己的窗口

        # 获取窗口信息
        try:
            window_text = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            x, y, x2, y2 = rect
            width = x2 - x
            height = y2 - y

            # 排除任务栏、桌面、开始菜单等系统窗口
            if class_name in ['Shell_TrayWnd', 'Progman', 'WorkerW', 'ApplicationFrameWindow',
                              'Windows.UI.Core.CoreWindow']:
                return True
            if not window_text and not class_name:  # 排除一些没有文本和类名的隐藏窗口
                return True
            if width <= 10 or height <= 10:  # 排除过小的窗口
                return True

            # 检查是否已在外部移动列表中
            if hwnd not in self.external_moving_windows:
                # 随机分配速度
                speed_x = random.choice(BOUNCE_SPEED_RANGE)
                speed_y = random.choice(BOUNCE_SPEED_RANGE)

                self.external_moving_windows[hwnd] = {
                    'x': x, 'y': y,
                    'speed_x': speed_x, 'speed_y': speed_y,
                    'width': width, 'height': height,
                    'text': window_text,
                    'class_name': class_name
                }
                print(f"发现外部窗口: HWND={hwnd}, 标题='{window_text}', 类名='{class_name}'")
        except Exception as e:
            # print(f"获取外部窗口 {hwnd} 信息失败: {e}") # 避免过多打印无关错误
            pass
        return True

    def find_external_windows(self):
        """扫描并记录可见的外部窗口"""
        if self.moving_active:
            self.external_moving_windows.clear()  # 清空旧列表，重新扫描
            win32gui.EnumWindows(self._enum_windows_proc, None)
            self.external_window_timer = self.root.after(int(EXTERNAL_WINDOW_ENUM_INTERVAL * 1000),
                                                         self.find_external_windows)

    def find_and_demote_java_windows(self):
        """
        扫描并强制降低Java窗口的Z轴顺序（置底）。
        """
        if not self.moving_active:
            return

        def demote_handler(hwnd, extra):
            if not win32gui.IsWindowVisible(hwnd):
                return True  # 跳过不可见窗口
            if self._is_our_window(hwnd):
                return True  # 跳过自己的窗口

            try:
                class_name = win32gui.GetClassName(hwnd)
                # 识别常见的Java Swing/AWT窗口类名
                if "SunAwtWindow" in class_name or "SunAwtFrame" in class_name:
                    # 强制将Java窗口置于所有窗口的底部
                    win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
            except Exception as e:
                pass  # 避免过多打印
            return True

        win32gui.EnumWindows(demote_handler, None)
        self.java_window_timer = self.root.after(int(JAVA_WINDOW_DEMOTE_INTERVAL * 1000),
                                                 self.find_and_demote_java_windows)

    def set_current_process_priority(self, priority_class):
        """设置当前进程的优先级"""
        try:
            current_process_handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(current_process_handle, priority_class)
            print(f"当前Python进程优先级已设置为: {self._priority_class_name(priority_class)}")
        except Exception as e:
            print(f"设置自身进程优先级失败: {e}. 请尝试以管理员身份运行。")

    def _priority_class_name(self, priority_class):
        """辅助函数，用于打印优先级名称"""
        if priority_class == NORMAL_PRIORITY_CLASS: return "NORMAL_PRIORITY_CLASS"
        if priority_class == IDLE_PRIORITY_CLASS: return "IDLE_PRIORITY_CLASS"
        if priority_class == HIGH_PRIORITY_CLASS: return "HIGH_PRIORITY_CLASS"
        if priority_class == REALTIME_PRIORITY_CLASS: return "REALTIME_PRIORITY_CLASS"
        if priority_class == BELOW_NORMAL_PRIORITY_CLASS: return "BELOW_NORMAL_PRIORITY_CLASS"
        if priority_class == ABOVE_NORMAL_PRIORITY_CLASS: return "ABOVE_NORMAL_PRIORITY_CLASS"
        return f"Unknown ({priority_class})"

    def disable_screensaver(self):
        """禁用系统屏保并保持显示器开启"""
        try:
            # 禁用屏保
            ctypes.windll.user32.SystemParametersInfoW(SPI_SETSCREENSAVEACTIVE, 0, 0, 0)
            print("系统屏保已禁用。")
            # 保持显示器开启
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_DISPLAY_REQUIRED)
            print("显示器已设置为保持开启。")
        except Exception as e:
            print(f"禁用屏保或保持显示器开启失败: {e}. 请确保程序以管理员身份运行。")

    def _update_all_moving_windows(self):
        """统一控制所有窗口的移动和碰撞"""
        while self.moving_active:
            # 更新自身创建的窗口
            windows_to_remove = []
            for info in self.windows[:]:  # 遍历副本以安全修改列表
                if not win32gui.IsWindow(info['hwnd']):
                    windows_to_remove.append(info)
                    continue

                x, y = info['x'], info['y']
                speed_x, speed_y = info['speed_x'], info['speed_y']
                width, height = info['width'], info['height']

                new_x = x + speed_x
                new_y = y + speed_y

                # 碰撞检测并反弹
                if new_x <= 0 or new_x + width >= screen_width:
                    speed_x *= -1
                    new_x = max(0, min(new_x, screen_width - width))  # 确保不超出边界
                    # 注意：此处不再调用 _play_sound
                if new_y <= 0 or new_y + height >= screen_height:
                    speed_y *= -1
                    new_y = max(0, min(new_y, screen_height - height))  # 确保不超出边界
                    # 注意：此处不再调用 _play_sound

                info['speed_x'] = speed_x
                info['speed_y'] = speed_y
                info['x'] = new_x
                info['y'] = new_y

                try:
                    # 更新窗口位置并保持在最顶层
                    win32gui.SetWindowPos(info['hwnd'], win32con.HWND_TOPMOST,
                                          int(new_x), int(new_y), 0, 0,
                                          win32con.SWP_NOSIZE)  # 不改变大小
                except Exception as e:
                    print(f"移动自身窗口 HWND {info['hwnd']} 出错: {e}")
                    windows_to_remove.append(info)

            for info in windows_to_remove:
                if info in self.windows:
                    self.windows.remove(info)

            # 更新外部窗口
            external_windows_to_remove = []
            for hwnd, info in list(self.external_moving_windows.items()):  # 遍历副本
                if not win32gui.IsWindow(hwnd):
                    external_windows_to_remove.append(hwnd)
                    continue

                try:
                    # 获取当前窗口实际位置，因为它们可能被用户或Java程序移动了
                    rect = win32gui.GetWindowRect(hwnd)
                    current_x, current_y, current_x2, current_y2 = rect

                    # 使用实际位置来计算下一步，而不是info中存储的旧位置
                    x = current_x
                    y = current_y
                    width = current_x2 - current_x
                    height = current_y2 - current_y

                    speed_x, speed_y = info['speed_x'], info['speed_y']

                    new_x = x + speed_x
                    new_y = y + speed_y

                    # 碰撞检测并反弹
                    if new_x <= 0 or new_x + width >= screen_width:
                        speed_x *= -1
                        new_x = max(0, min(new_x, screen_width - width))  # 确保不超出边界
                    if new_y <= 0 or new_y + height >= screen_height:
                        speed_y *= -1
                        new_y = max(0, min(new_y, screen_height - height))  # 确保不超出边界

                    info['speed_x'] = speed_x
                    info['speed_y'] = speed_y
                    # 注意：这里不更新 info['x'], info['y']，因为我们每次都从实际位置获取

                    # 移动外部窗口，但不改变其Z-order，因为它可能被Java程序控制，
                    # 我们的Java窗口打压逻辑会负责将其置底。
                    win32gui.SetWindowPos(hwnd, 0,  # 不指定Z-order，保持原样或由Java打压逻辑控制
                                          int(new_x), int(new_y), 0, 0,
                                          win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)  # 不改变大小，不激活
                except Exception as e:
                    print(f"移动外部窗口 HWND {hwnd} 出错: {e}")
                    external_windows_to_remove.append(hwnd)  # 移除问题窗口

            for hwnd_to_remove in external_windows_to_remove:
                if hwnd_to_remove in self.external_moving_windows:
                    del self.external_moving_windows[hwnd_to_remove]

            # 控制整体移动的更新频率
            time.sleep(0.03)  # 约 33 FPS

    def _start_moving(self):
        """启动窗口移动线程"""
        if not self.moving_active:
            self.moving_active = True
            self.moving_thread = threading.Thread(target=self._update_all_moving_windows, daemon=True)
            self.moving_thread.start()
            print("窗口移动线程已启动。")

    def _stop_moving(self):
        """停止窗口移动线程"""
        if self.moving_active:
            self.moving_active = False
            if self.moving_thread.is_alive():
                self.moving_thread.join(timeout=1.0)  # 等待线程结束
            print("窗口移动线程已停止。")

    def start(self):
        """启动程序"""
        print("开始创建窗口...")
        self.disable_screensaver()  # 激进策略：禁用屏保
        self.creation_timer = self.root.after(WINDOW_CREATION_DELAY_MS, self.create_window)
        self._start_moving()  # 启动统一的移动线程
        self.periodic_force_topmost()  # 启动自身窗口强制置顶定时器
        self.find_external_windows()  # 启动扫描外部窗口定时器 (负责将外部窗口加入移动列表)
        self.find_and_demote_java_windows()  # 启动降低Java窗口定时器 (专门针对Java窗口置底)

        # 启动背景音乐循环播放
        if self.background_music_loaded:
            try:
                pygame.mixer.music.play(-1)  # -1 表示无限循环播放
                print("背景音乐开始循环播放。")
            except Exception as e:
                print(f"背景音乐播放失败: {e}")

        self.root.mainloop()  # 进入Tkinter事件循环

    def cleanup(self):
        """清理资源"""
        print("正在清理资源...")
        if self.creation_timer:
            try:
                self.root.after_cancel(self.creation_timer)
            except tk.TclError:
                pass
        if self.force_topmost_timer:
            try:
                self.root.after_cancel(self.force_topmost_timer)
            except tk.TclError:
                pass
        if self.external_window_timer:
            try:
                self.root.after_cancel(self.external_window_timer)
            except tk.TclError:
                pass
        if self.java_window_timer:
            try:
                self.root.after_cancel(self.java_window_timer)
            except tk.TclError:
                pass

        self._stop_moving()
        for info in self.windows[:]:
            self._destroy_window(info)

        # 恢复屏保设置
        try:
            ctypes.windll.user32.SystemParametersInfoW(SPI_SETSCREENSAVEACTIVE, 1, 0, 0)
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)  # 恢复默认显示器状态
            print("屏保设置和显示器状态已恢复。")
        except Exception as e:
            print(f"恢复屏保设置或显示器状态失败: {e}. 可能是由于权限不足。")

        if pygame.mixer.get_init():
            pygame.mixer.music.stop()  # 停止背景音乐
            pygame.mixer.quit()
        try:
            if self.root and self.root.winfo_exists(): self.root.destroy()
        except tk.TclError:
            pass
        print("清理完成。")


if __name__ == "__main__":
    # --- 在程序实际启动前进行提权检查 ---
    if not ctypes.windll.shell32.IsUserAnAdmin():
        # 如果不是管理员，尝试以管理员权限重新运行
        # run_as_admin() 会在成功提权后退出当前非管理员进程
        # 所以如果它返回 False，表示提权失败或者用户取消了UAC
        if not run_as_admin():
            print("警告: 未获得管理员权限，部分功能（如禁用屏保）可能受限。程序将以当前权限继续运行。")
            # 如果你希望没有管理员权限就直接退出，可以取消下面这行的注释：
            # sys.exit(1)

    # 如果程序能够执行到这里，说明它要么已经是管理员，
    # 要么用户取消了UAC并且你选择了在没有管理员权限的情况下继续运行。

    manager = None
    try:
        manager = WindowManager()
        manager.start()
    except KeyboardInterrupt:
        print("程序被用户中断。")
    finally:
        if manager:
            manager.cleanup()