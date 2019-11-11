import os
import sys
from typing import List
import string

ARROW_UP = -1
ARROW_DOWN = -2
ARROW_RIGHT = -3
ARROW_LEFT = -4
CTRL_C = -5
CTRL_S = -6
BACKSPACE = -7
NEWLINE = -8
DELETE = -9
CTRL_L = -10
CTRL_K = -11

CTRL = -1000
ALT = -2000
SHIFT = -4000

WHITESPACE_CHARS = string.whitespace
WORD_CHAR = string.ascii_letters + '_$'


def get_leading_ws(text):
    return text[:len(text) - len(text.lstrip())]


def csi(data):
    sys.stdout.write('\x1b[' + data)


def yx_goto(y=0, x=0):
    csi(str(y + 1) + ';' + str(x + 1) + 'H')
    sys.stdout.flush()


EDITOR = None


class eline:
    def __init__(self, text=''):
        self.text = text
        self.disp_text = text
        self.dirty = True

    def split(self, index, tabulate=True):
        '''splits the line on index. 

        self remains the part AFTER the split, 
        returns the line representing the part BEFORE.'''
        txt = self.text
        if tabulate:
            self.text = get_leading_ws(txt) + txt[index:].lstrip()
        else:
            self.text = txt[index:]
        self.dirty = True
        return eline(txt[:index])

    def print(self, stdout, width, start):
        '''prints the line to stdout, up to `width` chars, starting at `start`'''
        if self.dirty:
            self._update_disp()
        stdout.write(self.disp_text[start: start+width])
        self.dirty = False

    def _update_disp(self):
        self.disp_text = self.text  # TODO handle tabs, special chars

    def insert(self, index, text):
        self.text = self.text[:index] + text + self.text[index:]
        self.dirty = True

    def append(self, text):
        self.text += text
        self.dirty = True

    def remove(self, start, end):
        self.text = self.text[:start] + self.text[end:]
        self.dirty = True


class efile:

    def __init__(self, path=None):
        self.unsaved = False
        self._lineoffset = 0
        self.lines: List[eline] = []
        self._dirty_before = 0
        self._dirty_after = 0
        self.path = path
        self._fileobj = None
        self.statusline_focus = False
        self.statusline = None
        if path:
            self._read_in(path)
        else:
            self.lines = [eline()]

    def _read_in(self, path):
        try:
            self._fileobj = open(path, 'r+')
        except:
            return
        # we need to split on '\n', not on os.linesep
        # because of 'universal newlines' thing
        for line in self._fileobj.read().split('\n'):
            self.lines.append(eline(line))

    def update_screen(self, offset, height, offset_y, width):
        for li in range(offset, offset + height):

            if li < len(self.lines) \
                    and not self.lines[li].dirty \
                    and (self._dirty_before < li < self._dirty_after):
                continue

            yx_goto(li - offset)
            csi('K')  # erase to end of line
            if li < len(self.lines):
                self.lines[li].print(sys.stdout, width, offset_y)
            else:
                sys.stdout.write('\x1b[34m~\x1b[0m')

        self._dirty_before = -1
        self._dirty_after = len(self.lines)
        sys.stdout.flush()

    def insert_text(self, row, col, text):
        self.unsaved = True
        if row < 0:
            row = 0
        if row >= len(self.lines):
            row = len(self.lines)
            self.lines.append(eline(text))

        else:
            self.lines[row].insert(col, text)

    def del_text(self, row, col, amount):
        self.unsaved = True
        while col + amount < 0:
            if row == 0:
                amount = -col
                break

            # append the rest to the previous line
            newcol = self.get_line_len(row-1)
            self.lines[row - 1].append(self.lines[row].text[col:])
            # remove the current line
            self.lines.pop(row)
            self._mark_dirty(after=row - 1)
            row = row - 1
            amount += col + 1
            col = newcol

        while col + amount > self.get_line_len(row):
            if row == len(self.lines)-1:
                amount = self.get_line_len(row) - col
                break

            # append the next line
            self.lines[row].append(self.lines[row + 1].text)
            # remove the next line
            self.lines.pop(row + 1)
            self._mark_dirty(after=row)
            amount -= 1

        curline: eline = self.lines[row]
        if amount < 0:
            col += amount
            amount = -amount

        curline.remove(col, col+amount)

        return row, col

    def _mark_dirty(self, before=None, after=None):
        if before is not None:
            self._dirty_before = max(self._dirty_before, before)
        if after is not None:
            self._dirty_after = min(self._dirty_after, after)

    def split_line(self, row, col, indent=True):
        curline: eline = self.lines[row]
        self.lines.insert(row, curline.split(col, indent))
        self._mark_dirty(after=row)

    def open_for_overwrite(self, path):
        try:
            self._fileobj = open(path, 'x')
            return True
        except:
            ans = ask(EDITOR, 'File existsm, overwrite? [y/N]')
            if ans and ans.lower().startswith('y'):
                self._fileobj = open(path, 'w')
                return True

        return False

    def save(self):
        if not self._fileobj:
            if not self.open_for_overwrite(self.path):
                return False
        self._fileobj.seek(0)
        self._fileobj.writelines(l.text + '\n' for l in self.lines[:-1])
        self._fileobj.write(self.lines[-1].text)
        self._fileobj.truncate()
        self._fileobj.flush()
        self.unsaved = False
        return True

    def save_as(self, path):
        if self._fileobj:
            self._fileobj.close()

        if self.open_for_overwrite(path):
            return self.save()

        return False

    def get_line_len(self, row):
        return len(self.lines[row].text) if row < len(self.lines) else 0

    def move_left(self, cur_row, cur_col):
        if cur_col > 0:
            return cur_row, cur_col - 1, True
        elif cur_row > 0:
            return cur_row - 1, self.get_line_len(cur_row - 1), True
        else:
            return 0, 0, False

    def move_right(self, cur_row, cur_col):
        if cur_col < self.get_line_len(cur_row):
            return cur_row, cur_col + 1, True
        elif cur_row < len(self.lines):
            return cur_row + 1, 0, True
        else:
            return len(self.lines), 0, False

    def __getitem__(self, loc):
        row, col = loc
        if row >= len(self.lines):
            return '\0'
        line = self.lines[row]
        if col >= len(line.text):
            return '\n'
        else:
            return self.lines[row].text[col]

    def find_word_prev(self, cur_row, cur_col):
        i = 0
        cur_row, cur_col, moved = self.move_left(cur_row, cur_col)
        if not moved:
            return cur_row, cur_col, i
        while self[cur_row, cur_col] in WHITESPACE_CHARS:
            cur_row, cur_col, moved = self.move_left(cur_row, cur_col)
            if not moved:
                break
            i += 1

        is_wc = self[cur_row, cur_col] in WORD_CHAR

        toret = cur_row, cur_col

        while True:
            cur_row, cur_col, moved = self.move_left(cur_row, cur_col)
            if not moved:
                break
            if (self[cur_row, cur_col] in WORD_CHAR) != is_wc or self[cur_row, cur_col] in WHITESPACE_CHARS:
                break
            else:
                toret = cur_row, cur_col
                i += 1

        return toret[0], toret[1], i

    def find_word_next(self, cur_row, cur_col):

        i = 0
        is_wc = self[cur_row, cur_col] in WORD_CHAR

        # skip current word
        while (self[cur_row, cur_col] in WORD_CHAR) == is_wc and self[cur_row, cur_col] not in WHITESPACE_CHARS:
            cur_row, cur_col, moved = self.move_right(cur_row, cur_col)
            if not moved:
                break
            i += 1

        # skip whitespace to next word
        while self[cur_row, cur_col] in WHITESPACE_CHARS:
            cur_row, cur_col, moved = self.move_right(cur_row, cur_col)
            if not moved:
                break
            i += 1

        return cur_row, cur_col, i

    def refresh_statusline(self):
        if self.statusline != None:
            return
        self.statusline_focus = False
        self.statusline = self.path or '<unnamed>'
        if self.unsaved:
            self.statusline += ' [*]'
        if self.path and not self._fileobj:
            self.statusline += ' [new]'


class editor:
    def __init__(self):
        self.running = True

        self.conw, self.conh = get_tty_wh()
        self.conh -= 1  # reserve one line for statusline

        self.cur_row, self.cur_col = 0, 0

        self.offset_row, self.offset_col = 0, 0


if os.name == 'nt':
    import msvcrt
    import win32

    def getch():
        c = msvcrt.getwch()
        if c == chr(0):
            c = msvcrt.getwch()
            if c == 'H':
                return ARROW_UP
            elif c == 'P':
                return ARROW_DOWN
            elif c == 'M':
                return ARROW_RIGHT
            elif c == 'K':
                return ARROW_LEFT
            elif c == 'S':
                return DELETE
            elif c == '\x8d':
                return CTRL + ARROW_UP
            elif c == '\x91':
                return CTRL + ARROW_DOWN
            elif c == 't':
                return CTRL + ARROW_RIGHT
            elif c == 's':
                return CTRL + ARROW_LEFT
            elif c == '\x93':
                return CTRL + DELETE

        elif c == '\x03':
            return CTRL_C
        elif c == '\x0b':
            return CTRL_K
        elif c == '\x0c':
            return CTRL_L
        elif c == '\x08':
            return BACKSPACE
        elif c == '\x13':
            return CTRL_S
        elif c == '\r':
            return NEWLINE

        return c

    def get_tty_wh():
        from ctypes import windll, create_string_buffer
        h = windll.kernel32.GetStdHandle(-12)
        csbi = create_string_buffer(22)
        res = windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)
        if res:
            import struct
            (_, _, _, _, _, left, top, right, bottom, _,
             _) = struct.unpack("hhhhHhhhhhh", csbi.raw)
            sizex = right - left + 1
            sizey = bottom - top + 1
        else:
            sizex = 90
            sizey = 90
        return sizex, sizey


def ask(e, question):
    yx_goto(e.conh + 1, 0)
    csi('42m')   # green bg
    csi('97m')  # white text
    csi('K')  # kill line

    sys.stdout.write(' ' + question + ' ')

    ans = ''
    index = 0

    while True:
        yx_goto(e.conh + 1, 2 + len(question))
        sys.stdout.write(ans + ' ')
        yx_goto(e.conh + 1, 2 + len(question) + index)
        c = getch()

        if c == CTRL_C:
            ans = None
            break
        elif c == NEWLINE:
            break
        elif c == BACKSPACE or c == DELETE:
            if len(ans) > 0:
                if c == BACKSPACE:
                    index -= 1
                ans = ans[:index] + ans[index + 1:]
        elif isinstance(c, str):
            ans = ans[:index] + c + ans[index:]
            index += 1

    csi('0m')
    return ans


def clamp(x, low, high):
    return min(max(low, x), high)


def clear_screen():
    csi('H')
    csi('J')
    sys.stdout.flush()


def perform_cmd(cmd, e, f):
    import shlex
    cmd = shlex.split(cmd)

    if cmd[0] == 'save':
        if len(cmd) > 1:
            if f.save_as(cmd[1]):
                f.statusline = 'Saved as ' + cmd[1]
            else:
                f.statusline_focus = True
                f.statusline = 'Not saved!'

        elif f.path:
            if f.save():
                f.statusline = 'Saved!'
            else:
                f.statusline_focus = True
                f.statusline = 'Not saved!'
        else:
            f.statusline = "No filename! Use 'save <filename>'"
            f.statusline_focus = True


def edit_file(file: efile):
    global EDITOR

    e = editor()
    EDITOR = e

    file.refresh_statusline()

    def _refreshdisp():
        file.update_screen(e.offset_row, e.conh, e.offset_col, e.conw)
        yx_goto(e.conh + 1)

        if file.statusline_focus:
            fgc = '41'
        else:
            fgc = '46'

        sys.stdout.write(
            '\x1b[' + fgc + 'm\x1b[97m\x1b[K ' + file.statusline[:e.conw-2] + '\x1b[0m')

        yx_goto(e.cur_row - e.offset_row, e.cur_col - e.offset_col)

    _refreshdisp()

    while e.running:
        c = getch()
        file.statusline = None
        if c == CTRL_C:
            if not file.unsaved:
                e.running = False
            else:
                file.statusline_focus = True
                file.statusline = 'Unsaved changes! Press ^C 2 more times to exit.'
                _refreshdisp()
                if getch() == CTRL_C:
                    file.statusline_focus = True
                    file.statusline = 'Unsaved changes! Press ^C 1 more time to exit.'
                    _refreshdisp()
                    if getch() == CTRL_C:
                        e.running = False
                    else:
                        file.statusline = 'Quit canceled ...'
                else:
                    file.statusline = 'Quit canceled ...'

        elif c == ARROW_UP:
            if e.cur_row > 0:
                e.cur_row -= 1
                e.cur_col = min(e.cur_col, file.get_line_len(e.cur_row))
                if e.cur_row < e.offset_row:
                    e.offset_row -= 1
                    file._mark_dirty(after=e.offset_row)
        elif c == ARROW_DOWN:
            if e.cur_row < len(file.lines) - 1:
                e.cur_row += 1
                e.cur_col = min(e.cur_col, file.get_line_len(e.cur_row))
                if (e.cur_row >= e.offset_row + e.conh):
                    e.offset_row += 1
                    file._mark_dirty(after=e.offset_row)
            else:
                e.cur_col = file.get_line_len(e.cur_row)
        elif c == ARROW_LEFT:
            if e.cur_col > 0:
                e.cur_col -= 1
        elif c == ARROW_RIGHT:
            if e.cur_col < file.get_line_len(e.cur_row):
                e.cur_col += 1
        elif c == CTRL + ARROW_LEFT:
            e.cur_row, e.cur_col, _ = file.find_word_prev(e.cur_row, e.cur_col)
        elif c == CTRL + ARROW_RIGHT:
            e.cur_row, e.cur_col, _ = file.find_word_next(e.cur_row, e.cur_col)
        elif c == CTRL + ARROW_UP:
            e.offset_row = max(0, e.offset_row - 1)
            e.cur_row = clamp(e.cur_row, e.offset_row,
                              e.offset_row + e.conh - 1)
            file._mark_dirty(after=e.offset_row)
        elif c == CTRL + ARROW_DOWN:
            e.offset_row = min(len(file.lines) - 1, e.offset_row + 1)
            e.cur_row = clamp(e.cur_row, e.offset_row,
                              e.offset_row + e.conh - 1)
            file._mark_dirty(after=e.offset_row)
        elif c == CTRL + DELETE:
            _, _, amount = file.find_word_next(e.cur_row, e.cur_col)
            e.cur_row, e.cur_col = file.del_text(e.cur_row, e.cur_col, amount)
        elif c == BACKSPACE:
            e.cur_row, e.cur_col = file.del_text(e.cur_row, e.cur_col, -1)
        elif c == DELETE:
            e.cur_row, e.cur_col = file.del_text(e.cur_row, e.cur_col, 1)
        elif c == NEWLINE:
            file.split_line(e.cur_row, e.cur_col)
            e.cur_row += 1
            e.cur_col = len(get_leading_ws((file.lines[e.cur_row].text)))
        elif c == CTRL_S:
            if not file.path:
                file.path = ask(e, 'filename?')
            if file.save():
                file.statusline = 'Saved!'
            else:
                file.statusline_focus = True
                file.statusline = 'Not saved!'
        elif c == CTRL_L:
            file._mark_dirty(after=0)
        elif c == CTRL_K:
            cmd = ask(e, '>')
            if cmd:
                perform_cmd(cmd, e, file)
        else:
            file.insert_text(e.cur_row, e.cur_col, c)
            e.cur_col += len(c)

        file.refresh_statusline()
        _refreshdisp()


def keytester():
    while True:
        c = getch()
        if c == CTRL_C:
            return

        print(repr(c))


def main(args):
    clear_screen()

    if len(args) > 1:
        file = efile(args[1])
    else:
        file = efile()

    edit_file(file)
    # keytester()

    clear_screen()


if __name__ == "__main__":
    import sys
    main(sys.argv)
