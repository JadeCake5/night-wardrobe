# -*- coding: utf-8 -*-
"""探测本机 Python 3.11+ 解释器。

stdout：合格路径按版本降序（WARDROBE_PYTHON 合格时置顶），一行一条。
stderr：每个候选的版本或失败原因。
无合格候选时退出码 1。

必须保持 Python 3.6 语法，以便旧解释器也能完成引导探测。
"""
import os
import re
import subprocess
import sys

MIN_VERSION = (3, 11, 0)
# 覆盖 -V:3.12、 -V:3.6-32、 -V:Astral/CPython3.14.6
LAUNCHER_RE = re.compile(r"^\s*-V:(\S+)\s+(.*)$")
PROBE_CODE = 'import sys; print("%d.%d.%d" % sys.version_info[:3])'


def eprint(msg):
    sys.stderr.write(msg + "\n")
    try:
        sys.stderr.flush()
    except Exception:
        pass


def is_store_stub(path):
    return "\\windowsapps\\" in path.replace("/", "\\").lower()


def run_capture(args):
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10,
        )
        return proc.returncode, proc.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def add_candidate(ordered, seen, raw, source):
    if not raw:
        return
    path = os.path.expandvars(raw.strip().strip('"'))
    if not path:
        return
    if is_store_stub(path):
        eprint("  已跳过  商店占位解释器        %s  (%s)" % (path, source))
        return
    if not os.path.isfile(path):
        eprint("  已跳过  文件不存在            %s  (%s)" % (path, source))
        return
    abs_path = os.path.abspath(path)
    key = os.path.normcase(abs_path)
    if key in seen:
        return
    seen.add(key)
    ordered.append((abs_path, source))


def collect_candidates():
    ordered = []
    seen = set()
    env_py = os.environ.get("WARDROBE_PYTHON")
    if env_py:
        add_candidate(ordered, seen, env_py, "WARDROBE_PYTHON")
    code, out = run_capture(["py", "-0p"])
    if code == 0 and out:
        for line in out.splitlines():
            match = LAUNCHER_RE.match(line)
            if not match:
                continue
            rest = match.group(2).strip()
            if rest.startswith("*"):
                rest = rest[1:].strip()
            add_candidate(ordered, seen, rest, "py -0p")
    for name in ("python", "python3"):
        code, out = run_capture(["where.exe", name])
        if code != 0 or not out:
            continue
        for line in out.splitlines():
            add_candidate(ordered, seen, line, "where %s" % name)
    return ordered


def probe_version(exe):
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "universal_newlines": True,
        "timeout": 10,
    }
    if os.name == "nt":
        # 0x08000000 = CREATE_NO_WINDOW，避免探测时闪出控制台
        kwargs["creationflags"] = 0x08000000
    try:
        proc = subprocess.run([exe, "-c", PROBE_CODE], **kwargs)
    except subprocess.TimeoutExpired:
        return None, "探测超时"
    except OSError as exc:
        return None, "无法启动: %s" % exc
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or ("退出码 %s" % proc.returncode)
        return None, err
    parts = raw.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None, "无法解析版本: %s" % raw
    return (int(parts[0]), int(parts[1]), int(parts[2])), None


def main():
    eprint("[find_python] 正在探测本机 Python 解释器")
    qualified = []
    for path, source in collect_candidates():
        version, err = probe_version(path)
        if err is not None:
            eprint("  探测失败  %-16s  %s  (%s)" % (err, path, source))
            continue
        ver_text = "%d.%d.%d" % version
        if version >= MIN_VERSION:
            eprint("  合格      %-16s  %s  (%s)" % (ver_text, path, source))
            qualified.append((version, path, source))
        else:
            eprint(
                "  版本不足  %-16s  需要 >= 3.11  %s  (%s)"
                % (ver_text, path, source)
            )
    qualified.sort(key=lambda item: item[0], reverse=True)
    env_first = [item for item in qualified if item[2] == "WARDROBE_PYTHON"]
    others = [item for item in qualified if item[2] != "WARDROBE_PYTHON"]
    if os.environ.get("WARDROBE_PYTHON") and not env_first:
        eprint("[find_python] WARDROBE_PYTHON 指定的解释器版本不足或不可用")
        return 1
    ordered = env_first + others
    if not ordered:
        eprint("[find_python] 未找到 Python 3.11 或更高版本")
        return 1
    for _version, path, _source in ordered:
        sys.stdout.write(path + "\n")
    try:
        sys.stdout.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
