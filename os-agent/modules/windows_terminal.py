# import time
# import pyautogui
# import pygetwindow as gw
# import pyperclip
# # 这个文件是将本地终端进行显示增强真实效果为了视频演示使用，没有其他功能
# pyautogui.FAILSAFE = True
# class WindowsTerminal:
#     def __init__(self, terminal_title=None):
#         self.terminal_title = terminal_title
#         self.terminal_window = None
#     def find_terminal(self):
#         all_windows = gw.getAllWindows()
#         for w in all_windows:
#             title = w.title
#             if not title:
#                 continue
#             if "u@" in title or "192.168" in title:
#                 if "Anaconda" not in title and "streamlit" not in title.lower():
#                     self.terminal_window = w
#                     return True
#         return False
#     def focus(self):
#         if not self.terminal_window:
#             if not self.find_terminal():
#                 return False
#         try:
#             if self.terminal_window.isMinimized:
#                 self.terminal_window.restore()
#                 time.sleep(0.1)
#             self.terminal_window.activate()
#             time.sleep(0.12)
#             return True
#         except Exception:
#             return False
#     def render_execution(self, command, output=""):
#         if not self.focus():
#             return False
#         pyautogui.hotkey("ctrl", "c")
#         time.sleep(0.08)
#         normalized_command = (command or "").strip()
#         rendered_output = (output or "(命令执行成功，无输出)").strip()
#         marker = "__CODEX_VIEW__"
#         while marker in normalized_command or marker in rendered_output:
#             marker += "_X"
#         display_script = f"cat <<'{marker}'\n$ {normalized_command}\n{rendered_output}\n{marker}"
#         pyperclip.copy(display_script)
#         pyautogui.hotkey("ctrl", "v")
#         time.sleep(0.08)
#         pyautogui.press("enter")
#         time.sleep(0.18)
#         return True
# terminal = WindowsTerminal()
