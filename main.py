import curses
import json
import requests
import threading
import queue
from datetime import datetime
from collections import deque
from curses.textpad import Textbox, rectangle
from urllib3.util.retry import Retry

class CurlClient:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.history = deque(maxlen=10)
        self.current_method = "GET"
        self.current_url = ""
        self.headers = {}
        self.body = ""
        self.last_response = None
        self.request_in_progress = False
        self.response_queue = queue.Queue()
        self.min_height = 24
        self.min_width = 80
        self.selected_field = 0
        self.panels = [
            {'name': 'method', 'y': 2, 'x': 2, 'h': 3, 'w': 30, 'label': 'Method'},
            {'name': 'url', 'y': 6, 'x': 2, 'h': 3, 'w': 70, 'label': 'URL'},
            {'name': 'headers', 'y': 10, 'x': 2, 'h': 6, 'w': 45, 'label': 'Headers (JSON)'},
            {'name': 'body', 'y': 10, 'x': 48, 'h': 6, 'w': 45, 'label': 'Body (JSON)'},
            {'name': 'response', 'y': 17, 'x': 2, 'h': 8, 'w': 90, 'label': 'Response'}
        ]
        self.init_ui()

    def init_ui(self):
        curses.curs_set(1)
        self.stdscr.clear()
        self.check_window_size()
        self.draw_main_border()
        self.draw_panels()
        self.update_display()
        self.stdscr.refresh()

    def check_window_size(self):
        height, width = self.stdscr.getmaxyx()
        if height < self.min_height or width < self.min_width:
            self.stdscr.addstr(0, 0, "Terminal too small! Please resize to at least 80x24")
            self.stdscr.refresh()
            raise curses.error("Terminal too small")

    def draw_main_border(self):
        self.stdscr.border()
        title = " CurseClient - Terminal API Client (q to quit) "
        try:
            self.stdscr.addstr(0, 2, title, curses.color_pair(1) | curses.A_BOLD)
            help_text = "←→: Methods | ↑↓: Fields | Enter: Edit | F5: Send Request"
            self.stdscr.addstr(curses.LINES - 1, 2, help_text, curses.color_pair(3))
        except curses.error:
            pass

    def draw_panels(self):
        for panel in self.panels:
            y, x = panel['y'], panel['x']
            try:
                self.stdscr.addstr(y - 1, x, f" {panel['label']} ", curses.color_pair(1))
                rectangle(self.stdscr, y, x - 1, y + panel['h'], x + panel['w'])
            except curses.error:
                pass

    def update_display(self):
        self.clear_panels()
        self.draw_method_selection()
        self.draw_url_field()
        self.draw_headers_and_body_previews()
        self.draw_response_panel()
        self.highlight_selected_field()
        self.stdscr.refresh()

    def clear_panels(self):
        for panel in self.panels:
            for i in range(panel['h']):
                try:
                    self.stdscr.addstr(panel['y'] + i, panel['x'], " " * panel['w'])
                except curses.error:
                    pass

    def draw_method_selection(self):
        method_panel = self.panels[0]
        methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        x_pos = method_panel['x']
        for method in methods:
            color = curses.color_pair(2) if method == self.current_method else curses.color_pair(1)
            if self.selected_field == 0:
                color |= curses.A_BOLD
            try:
                self.stdscr.addstr(method_panel['y'], x_pos, f" {method} ", color)
            except curses.error:
                pass
            x_pos += len(method) + 2

    def draw_url_field(self):
        url_panel = self.panels[1]
        url_display = (self.current_url[:url_panel['w'] - 4] + "..." 
                       if len(self.current_url) > url_panel['w'] - 4 else self.current_url)
        url_color = curses.color_pair(2) if self.selected_field == 1 else curses.A_NORMAL
        try:
            self.stdscr.addstr(url_panel['y'], url_panel['x'], url_display, url_color)
        except curses.error:
            pass

    def draw_headers_and_body_previews(self):
        headers_panel = self.panels[2]
        body_panel = self.panels[3]

        headers_str = json.dumps(self.headers, indent=2, default=str)
        headers_preview = (headers_str[:headers_panel['w'] * 3] + "..." 
                           if len(headers_str) > headers_panel['w'] * 3 else headers_str)
        for i, line in enumerate(headers_preview.split('\n')):
            if i < headers_panel['h']:
                try:
                    self.stdscr.addstr(headers_panel['y'] + i, headers_panel['x'], line[:headers_panel['w']])
                except curses.error:
                    pass

        body_preview = self.body
        if self.body:
            try:
                body_preview = json.dumps(json.loads(self.body), indent=2, default=str)
            except Exception:
                pass
        body_preview = (body_preview[:body_panel['w'] * 3] + "..." 
                        if len(body_preview) > body_panel['w'] * 3 else body_preview)
        for i, line in enumerate(body_preview.split('\n')):
            if i < body_panel['h']:
                try:
                    self.stdscr.addstr(body_panel['y'] + i, body_panel['x'], line[:body_panel['w']])
                except curses.error:
                    pass

    def draw_response_panel(self):
        response_panel = self.panels[4]
        if self.request_in_progress:
            loading_text = "Loading..."
            try:
                self.stdscr.addstr(response_panel['y'], response_panel['x'], loading_text, curses.color_pair(3))
            except curses.error:
                pass
        elif self.last_response:
            self.display_response(self.last_response)

    def highlight_selected_field(self):
        for i, panel in enumerate(self.panels):
            if i == self.selected_field and i not in [0, 4]:
                try:
                    self.stdscr.addstr(panel['y'] - 1, panel['x'], f" {panel['label']} ", curses.color_pair(2))
                except curses.error:
                    pass

    def edit_field(self):
        if self.selected_field == 1:
            self.edit_url()
        elif self.selected_field == 2:
            self.edit_headers()
        elif self.selected_field == 3:
            self.edit_body()

    def cycle_method(self, direction):
        methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        current_index = methods.index(self.current_method)
        new_index = (current_index + direction) % len(methods)
        self.current_method = methods[new_index]

    def edit_url(self):
        """Edit the URL field."""
        panel = self.panels[1]
        win = curses.newwin(1, panel['w'], panel['y'], panel['x'])
        try:
            win.addstr(0, 0, self.current_url)
        except curses.error:
            pass
        box = Textbox(win)
        box.edit()
        self.current_url = box.gather().strip()

    def edit_headers(self):
        self.headers = self.edit_json_field(2, self.headers)

    def edit_body(self):
        self.body = self.edit_json_field(3, self.body)

    def edit_json_field(self, field_index, initial_value):
        panel = self.panels[field_index]
        text = json.dumps(initial_value, indent=2, default=str) if initial_value else ""
        win = curses.newwin(panel['h'], panel['w'], panel['y'], panel['x'])
        try:
            win.addstr(0, 0, text)
        except curses.error:
            pass
        box = Textbox(win)
        box.edit()
        edited_text = box.gather().strip()
        try:
            if field_index == 2:
                return json.loads(edited_text)
            else:
                parsed = json.loads(edited_text)
                return json.dumps(parsed, indent=2, default=str)
        except json.JSONDecodeError as e:
            self.show_error(f"JSON Error: {str(e)}")
            return initial_value
        except Exception as e:
            self.show_error(str(e))
            return edited_text

    def send_request(self):
        if self.request_in_progress:
            self.show_status("Request already in progress, please wait...", curses.color_pair(3))
            return
        if not self.current_url:
            self.show_status("URL cannot be empty", curses.color_pair(5))
            return
        self.request_in_progress = True
        self.last_response = None
        self.show_status("Sending request...", curses.color_pair(4))
        thread = threading.Thread(target=self._do_send_request)
        thread.daemon = True
        thread.start()


    def _do_send_request(self):
        try:
            session = requests.Session()
            retry_strategy = Retry(total=0, backoff_factor=0)
            adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
            session.mount('http://', adapter)
            session.mount('https://', adapter)
            
            json_body = None
            if self.body:
                try:
                    json_body = json.loads(self.body)
                except Exception as e:
                    raise ValueError("Invalid JSON body: " + str(e))
            
            response = session.request(
                method=self.current_method,
                url=self.current_url,
                headers=self.headers,
                json=json_body,
                timeout=5
            )
            
            content_type = response.headers.get('content-type', '')
            if 'application/json' in content_type:
                body_content = response.json()
            else:
                body_content = response.text
            
            result = {
                'timestamp': datetime.now().isoformat(),
                'status': response.status_code,
                'reason': response.reason,
                'headers': dict(response.headers),
                'body': body_content
            }
            self.response_queue.put((result, None))
        except requests.exceptions.RequestException as e:
            error_message = str(e)
            if "Max retries exceeded" in error_message:
                error_message = "Connection failed: max retries exceeded. Check URL or network."
            self.response_queue.put((None, error_message))
        except Exception as e:
            self.response_queue.put((None, str(e)))
        finally:
            self.request_in_progress = False

    def display_response(self, response):
        panel = self.panels[4]
        try:
            if response.get('error'):
                text = response['error']
            else:
                text = json.dumps(response, indent=2, default=str)
        except Exception:
            text = str(response)
        lines = text.split('\n')
        for i in range(panel['h']):
            try:
                if i < len(lines):
                    self.stdscr.addstr(panel['y'] + i, panel['x'], lines[i][:panel['w']])
                else:
                    self.stdscr.addstr(panel['y'] + i, panel['x'], " " * panel['w'])
            except curses.error:
                pass

    def show_status(self, message, color=None):
        if color is None:
            color = curses.color_pair(3)
        max_width = curses.COLS - 4
        message = message[:max_width]
        status_line = curses.LINES - 2
        try:
            self.stdscr.addstr(status_line, 2, " " * max_width)
            self.stdscr.addstr(status_line, 2, message, color)
            self.stdscr.refresh()
        except curses.error:
            pass

    def show_error(self, message):
        self.show_status(message, curses.color_pair(5))

    def handle_resize(self):
        self.stdscr.clear()
        curses.resizeterm(*self.stdscr.getmaxyx())
        self.init_ui()

    def run(self):
        self.stdscr.timeout(100)
        while True:
            self.update_display()
            try:
                result, error = self.response_queue.get_nowait()
                if error:
                    self.last_response = {"error": error}
                    self.show_status(f"Error: {error}", curses.color_pair(5))
                else:
                    self.last_response = result
                    color = curses.color_pair(4) if result['status'] < 400 else curses.color_pair(5)
                    self.show_status(f"{result['status']} {result.get('reason', '')}", color)
            except queue.Empty:
                pass
            key = self.stdscr.getch()
            if key == -1:
                continue
            try:
                if key == ord('q'):
                    break
                elif key == curses.KEY_UP:
                    self.selected_field = max(0, self.selected_field - 1)
                elif key == curses.KEY_DOWN:
                    self.selected_field = min(3, self.selected_field + 1)
                elif key == curses.KEY_LEFT and self.selected_field == 0:
                    self.cycle_method(-1)
                elif key == curses.KEY_RIGHT and self.selected_field == 0:
                    self.cycle_method(1)
                elif key in [curses.KEY_ENTER, 10, 13]:
                    self.edit_field()
                elif key == curses.KEY_F5:
                    self.send_request()
                elif key == curses.KEY_RESIZE:
                    self.handle_resize()
            except Exception as e:
                self.show_error(f"Error: {str(e)}")


def main(stdscr):
    curses.curs_set(1)
    curses.use_default_colors()
    curses.start_color()
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_RED, curses.COLOR_BLACK)
    client = CurlClient(stdscr)
    client.run()


if __name__ == "__main__":
    curses.wrapper(main)
