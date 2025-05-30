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

# --- 配置区 ---
TOTAL_WINDOWS = 35 # 程序自身创建的窗口总数
WINDOW_CREATION_DELAY_MS = 400  # 创建窗口之间的延迟（毫秒）
BOUNCE_SPEED_RANGE = [-3, -2, 2, 3] # 窗口弹跳速度（像素/步）范围
SOUND_FILE = "mymp3.mp3" # 要播放的音频文件名
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp') # 支持的图片文件扩展名
EXTERNAL_WINDOW_ENUM_INTERVAL = 1.0 # 秒 - 扫描外部窗口的频率
# --- 配置区结束 ---

# 初始化屏幕尺寸
screen_width, screen_height = pyautogui.size()

# !!! 关键修改区域 !!!
# 获取应用程序的根目录。
# 如果程序是被 PyInstaller 打包的，sys.executable 就是 exe 文件的完整路径。
# 如果是直接运行 .py 脚本，os.path.abspath(__file__) 是脚本文件的完整路径。
# os.path.dirname() 用于获取文件所在的目录。
APP_ROOT_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

print(f"应用程序根目录: {APP_ROOT_DIR}")

class WindowManager:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.windows = []
        self.own_hwnds = set()
        self.own_hwnds.add(self.root.winfo_id())

        # !!! 修改 _find_image_files 的调用方式，传入 APP_ROOT_DIR !!!
        self.image_paths = self._find_image_files(APP_ROOT_DIR)
        if not self.image_paths:
            print("错误：当前目录或指定目录未找到图片文件。")
            print(f"查找的扩展名: {', '.join(IMAGE_EXTENSIONS)}")
            sys.exit() # 如果没有找到图片，程序直接退出
        self.num_images = len(self.image_paths)
        self.use_random_images = (TOTAL_WINDOWS % self.num_images != 0)
        print(f"找到 {self.num_images} 个图片文件。{'随机使用' if self.use_random_images else '循环使用'}.")
        self.loaded_images = {}

        # 初始化音频
        try:
            # !!! 修改音频文件路径，确保使用 APP_ROOT_DIR !!!
            sound_full_path = os.path.join(APP_ROOT_DIR, SOUND_FILE)
            pygame.mixer.init()
            pygame.mixer.set_num_channels(1)
            self.sound = pygame.mixer.Sound(sound_full_path)
            print(f"音频系统已初始化。声音文件 '{sound_full_path}' 加载成功。")
        except Exception as e:
            # 如果音频文件加载失败，打印错误并禁用音频功能
            print(f"音频初始化或加载声音文件 '{os.path.join(APP_ROOT_DIR, SOUND_FILE)}' 失败: {e}. 音频功能将被禁用。")
            self.sound = None

        # --- 新增：用于存储外部窗口及其速度 ---
        self.external_moving_windows = {}

        # 窗口创建控制
        self.created_window_count = 0
        self.creation_timer = None

        # 统一的移动控制
        self.moving_active = False
        self.move_thread = None

    # !!! 修改 _find_image_files 函数，接受 base_dir 参数 !!!
    def _find_image_files(self, base_dir):
        """查找指定目录中的图片文件"""
        image_files = []
        try:
            # 遍历 base_dir 目录下的文件
            for fname in os.listdir(base_dir):
                if fname.lower().endswith(IMAGE_EXTENSIONS):
                    image_files.append(os.path.join(base_dir, fname))
        except FileNotFoundError:
            print(f"错误: 无法访问目录 {base_dir}。请确保目录存在且有读取权限。")
        except Exception as e:
             print(f"错误：扫描目录查找图片时出错: {e}")
        return image_files

    def _load_image(self, image_path):
        """加载图片文件，返回 PIL Image 和 PhotoImage 对象"""
        if image_path in self.loaded_images:
            return self.loaded_images[image_path]
        try:
            pil_image = Image.open(image_path)
            photo_image = ImageTk.PhotoImage(pil_image)
            self.loaded_images[image_path] = (pil_image, photo_image)
            return pil_image, photo_image
        except FileNotFoundError:
            print(f"错误：图片文件 '{image_path}' 未找到。")
            return None, None
        except Exception as e:
            print(f"错误：加载图片 '{image_path}' 失败: {e}")
            return None, None

    def _get_image_for_window(self):
        """根据分配策略选择一个图片路径"""
        if not self.image_paths: return None
        if self.use_random_images:
            return random.choice(self.image_paths)
        else:
            image_index = self.created_window_count % self.num_images
            return self.image_paths[image_index]

    def create_window(self):
        """创建程序自身的图片窗口"""
        if self.created_window_count >= TOTAL_WINDOWS:
             if self.creation_timer: self.root.after_cancel(self.creation_timer)
             return

        image_path = self._get_image_for_window()
        if not image_path: return

        pil_image, photo_image = self._load_image(image_path)
        if not pil_image or not photo_image:
            # 如果图片加载失败，直接跳过创建此窗口并尝试下一个
            print(f"警告：图片加载失败 ({image_path})，跳过创建此窗口。")
            self.created_window_count += 1
            if self.created_window_count < TOTAL_WINDOWS:
                self.creation_timer = self.root.after(WINDOW_CREATION_DELAY_MS, self.create_window)
            return

        window_width, window_height = pil_image.size

        try:
            window = Toplevel(self.root)
            window.overrideredirect(1) # 无边框
            window.attributes('-topmost', True) # 始终置顶

            # 随机位置，确保窗口完全在屏幕内
            max_x = max(0, screen_width - window_width)
            max_y = max(0, screen_height - window_height)
            x = random.randint(0, max_x)
            y = random.randint(0, max_y)
            window.geometry(f"+{x}+{y}")

            label = tk.Label(window, image=photo_image, bd=0)
            label.pack()

            channel = None
            if self.sound: # 如果声音加载成功
                channel = pygame.mixer.find_channel()
                if channel: channel.play(self.sound)

            hwnd = window.winfo_id()
            self.own_hwnds.add(hwnd) # 记录自己的窗口句柄

            window_info = {
                'window': window, 'label': label, 'photo': photo_image,
                'hwnd': hwnd, 'channel': channel,
                'width': window_width, 'height': window_height,
                'dx': random.choice(BOUNCE_SPEED_RANGE),
                'dy': random.choice(BOUNCE_SPEED_RANGE)
            }
            self.windows.append(window_info)
            self.created_window_count += 1

            if self.created_window_count < TOTAL_WINDOWS:
                self.creation_timer = self.root.after(WINDOW_CREATION_DELAY_MS, self.create_window)

        except Exception as e:
            print(f"错误：创建第 {self.created_window_count} 个窗口时出错: {e}")
            # 即使出错也尝试继续创建下一个窗口，直到达到总数
            if self.created_window_count < TOTAL_WINDOWS:
                 self.creation_timer = self.root.after(WINDOW_CREATION_DELAY_MS, self.create_window)

    def _destroy_window(self, window_info):
        """销毁程序自身创建的窗口"""
        try:
            if window_info['window'].winfo_exists(): window_info['window'].destroy()
        except tk.TclError: pass # 窗口可能已经被销毁
        self.own_hwnds.discard(window_info['hwnd']) # 从句柄列表中移除
        if window_info in self.windows: self.windows.remove(window_info) # 从窗口信息列表中移除

    def _update_external_window_list(self):
        """使用EnumWindows查找外部窗口并添加到移动列表"""
        try:
            def enum_handler(hwnd, _):
                # 过滤掉不可见、无标题的窗口和程序自身的窗口
                if (win32gui.IsWindowVisible(hwnd) and
                    win32gui.GetWindowText(hwnd) != "" and
                    hwnd not in self.own_hwnds):
                    if hwnd not in self.external_moving_windows:
                        self.external_moving_windows[hwnd] = (
                            random.choice(BOUNCE_SPEED_RANGE),
                            random.choice(BOUNCE_SPEED_RANGE)
                        )
            win32gui.EnumWindows(enum_handler, None)

            # 移除已关闭的外部窗口
            current_external_hwnds = list(self.external_moving_windows.keys())
            for hwnd in current_external_hwnds:
                if not win32gui.IsWindow(hwnd):
                    del self.external_moving_windows[hwnd]

        except Exception as e:
            print(f"枚举外部窗口时出错: {e}")

    def _start_moving(self):
        """启动统一的移动线程"""
        if not self.move_thread or not self.move_thread.is_alive():
            self.moving_active = True
            self.move_thread = threading.Thread(target=self._update_all_moving_windows, daemon=True) # 设为守护线程
            self.move_thread.start()

    def _stop_moving(self):
        """停止统一的移动线程"""
        self.moving_active = False
        if self.move_thread and self.move_thread.is_alive():
            self.move_thread.join(timeout=1.0) # 等待线程结束

    def _update_all_moving_windows(self):
        """线程函数：更新所有需要移动的窗口（包括自身的和外部的）"""
        last_enum_time = time.time()

        while self.moving_active:
            current_time = time.time()

            # --- 1. 更新程序自身创建的窗口 ---
            # 复制一份列表以避免在迭代时修改
            own_windows_to_update = self.windows[:]
            for info in own_windows_to_update:
                if not self.moving_active: break # 检查停止信号
                hwnd = info['hwnd']
                w, h = info['width'], info['height']
                dx, dy = info['dx'], info['dy']
                try:
                    if not win32gui.IsWindow(hwnd): # 检查窗口是否仍然存在
                        self.root.after(0, self._destroy_window, info) # 回到主线程销毁窗口
                        continue
                    rect = win32gui.GetWindowRect(hwnd)
                    x, y = rect[0], rect[1]
                    new_x, new_y = x + dx, y + dy

                    # 边界检测和反弹
                    if new_x < 0: new_x, dx = 0, abs(dx)
                    elif new_x + w > screen_width: new_x, dx = screen_width - w, -abs(dx)
                    if new_y < 0: new_y, dy = 0, abs(dy)
                    elif new_y + h > screen_height: new_y, dy = screen_height - h, -abs(dy)

                    info['dx'], info['dy'] = dx, dy # 更新速度
                    # 移动窗口并保持在最顶层
                    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST,
                                          int(new_x), int(new_y), 0, 0,
                                          win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
                except (win32gui.error, tk.TclError) as e:
                    # 窗口可能已意外关闭或Tkinter错误
                    if info in self.windows: self.root.after(0, self._destroy_window, info)
                except Exception as e:
                    print(f"移动自身窗口 {hwnd} 发生意外错误: {e}")
                    if info in self.windows: self.root.after(0, self._destroy_window, info)

            if not self.moving_active: break # 再次检查停止信号

            # --- 2. 定期更新外部窗口列表 ---
            if current_time - last_enum_time > EXTERNAL_WINDOW_ENUM_INTERVAL:
                self._update_external_window_list()
                last_enum_time = current_time

            # --- 3. 更新外部窗口 ---
            external_hwnds_to_update = list(self.external_moving_windows.keys())
            for hwnd in external_hwnds_to_update:
                if not self.moving_active: break # 检查停止信号
                try:
                    if hwnd not in self.external_moving_windows: continue # 确保窗口还在列表中

                    dx, dy = self.external_moving_windows[hwnd]

                    rect = win32gui.GetWindowRect(hwnd)
                    x, y = rect[0], rect[1]
                    w, h = rect[2] - x, rect[3] - y

                    if w <= 0 or h <= 0: # 窗口无效或最小化
                        del self.external_moving_windows[hwnd]
                        continue

                    new_x, new_y = x + dx, y + dy

                    # 边界检测和反弹
                    if new_x < 0: new_x, dx = 0, abs(dx)
                    elif new_x + w > screen_width: new_x, dx = screen_width - w, -abs(dx)
                    if new_y < 0: new_y, dy = 0, abs(dy)
                    elif new_y + h > screen_height: new_y, dy = screen_height - h, -abs(dy)

                    self.external_moving_windows[hwnd] = (dx, dy) # 更新速度

                    # 移动窗口，不改变其Z序和激活状态
                    win32gui.SetWindowPos(hwnd, 0,
                                          int(new_x), int(new_y), 0, 0,
                                          win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)

                except win32gui.error: # 窗口可能已关闭
                    if hwnd in self.external_moving_windows:
                        del self.external_moving_windows[hwnd]
                except Exception as e: # 捕获其他意外错误
                    print(f"移动外部窗口 HWND {hwnd} 出错: {e}")
                    if hwnd in self.external_moving_windows:
                        del self.external_moving_windows[hwnd] # 移除问题窗口

            # 控制整体移动的更新频率
            time.sleep(0.03) # 约 33 FPS

    def start(self):
        """启动程序"""
        print("开始创建窗口...")
        self.creation_timer = self.root.after(WINDOW_CREATION_DELAY_MS, self.create_window)
        self._start_moving() # 启动统一的移动线程
        self.root.mainloop() # 进入Tkinter事件循环

    def cleanup(self):
        """清理资源"""
        print("正在清理资源...")
        if self.creation_timer:
            try: self.root.after_cancel(self.creation_timer)
            except tk.TclError: pass
        self._stop_moving() # 停止移动线程
        for info in self.windows[:]: # 销毁自身创建的窗口
             self._destroy_window(info)
        # 仅当 mixer 被成功初始化时才调用 quit
        if pygame.mixer.get_init():
            pygame.mixer.quit() # 关闭音频系统
        try:
            if self.root and self.root.winfo_exists(): self.root.destroy() # 销毁根窗口
        except tk.TclError: pass
        print("清理完成。")


if __name__ == "__main__":
    try:
        screen_width, screen_height = pyautogui.size()
    except Exception as e:
        print(f"无法获取屏幕尺寸: {e}")
        sys.exit() # 获取屏幕尺寸失败，程序无法运行，直接退出

    manager = WindowManager()
    try:
        manager.start()
    except KeyboardInterrupt:
        print("\n检测到 Ctrl+C，正在退出...")
    finally:
        manager.cleanup()