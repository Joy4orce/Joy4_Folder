"""
Joy4_Folder
- Flatten subfolder contents into a parent folder
- Translate Japanese file/folder names to Korean via Claude CLI (Haiku)
- Convert WAV / FLAC files to MP3 via ffmpeg
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import (
    BOTH, END, LEFT, RIGHT, X, Y, W, E,
    Button, Checkbutton, Entry, Frame, IntVar, Label,
    Radiobutton, Scrollbar, StringVar, Text, Tk, filedialog, messagebox,
)
from tkinter import ttk

CONFIG_PATH = Path(__file__).parent / "config.json"
IS_WINDOWS = sys.platform == "win32"
# Suppress flashing console windows when shelling out from a pythonw GUI
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0

DEFAULT_CONFIG = {
    "conflict_mode": "rename",          # overwrite | rename | skip
    "ffmpeg_path": "ffmpeg",
    "claude_path": "claude",
    "claude_model": "claude-haiku-4-5",
    "delete_originals_after_convert": False,
    "recursive_translate": False,
    "recursive_convert": False,
    "recursive_subtitle": False,
    # Translation engine: "claude" (CLI) | "gemma4" (local koboldcpp at OpenAI-compatible endpoint)
    "translate_engine": "claude",
    "gemma4_url": "http://localhost:5001/v1/chat/completions",
    "gemma4_temperature": 0.1,
    "gemma4_repeat_penalty": 1.05,
    # Cap on generated tokens per request. Long file names need plenty of room
    # or the JSON reply gets cut off mid-array and fails to parse.
    "gemma4_max_tokens": 4096,
}

JAPANESE_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")
ILLEGAL_FN_CHARS = '<>:"/\\|?*'
TRANSLATE_BATCH = 10

# Subtitle files sometimes carry the media extension too (name.mp3.vtt) and then
# fail to pair with the media file (name.mp3). Stripping the embedded media
# extension fixes it (name.vtt).
SUBTITLE_EXTS = (".vtt", ".srt", ".ass", ".ssa", ".smi", ".sub", ".lrc", ".sbv")
MEDIA_EXTS = (
    ".mp3", ".mp4", ".mkv", ".avi", ".flac", ".wav", ".m4a", ".webm", ".mov",
    ".wmv", ".flv", ".opus", ".aac", ".ogg", ".m4v", ".ts", ".mpg", ".mpeg",
)


# ---------- config ----------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------- helpers ----------

def resolve_conflict(target: Path, mode: str):
    """Return path to write to, or None if should skip."""
    if not target.exists():
        return target
    if mode == "overwrite":
        return target
    if mode == "skip":
        return None
    # rename: append _1, _2, ...
    stem, suffix, parent = target.stem, target.suffix, target.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def has_japanese(s: str) -> bool:
    return bool(JAPANESE_RE.search(s))


def safe_filename(name: str) -> str:
    for c in ILLEGAL_FN_CHARS:
        name = name.replace(c, "_")
    return name.strip(". ").strip() or "untitled"


# ---------- feature 1: flatten ----------

def flatten_folder(root: Path, conflict_mode: str, log, progress) -> None:
    if not root.is_dir():
        log(f"[오류] {root}은(는) 폴더가 아닙니다.")
        return

    # count files in subfolders first (excluding root level)
    total = 0
    for cur, _subs, files in os.walk(root):
        if Path(cur) == root:
            continue
        total += len(files)

    if total == 0:
        log("[펼치기] 하위폴더에 옮길 파일이 없습니다.")
        return

    log(f"[펼치기] 대상 파일 {total}개 발견.")
    progress(0, total, "이동 중")

    moved = skipped = failed = 0
    done = 0

    # bottom-up so we can delete dirs as they empty out
    for current_dir, _subdirs, files in os.walk(root, topdown=False):
        current = Path(current_dir)
        if current == root:
            continue
        for fname in files:
            src = current / fname
            target = root / fname
            dest = resolve_conflict(target, conflict_mode)
            if dest is None:
                log(f"  건너뛰기: {src.relative_to(root)} (대상 존재)")
                skipped += 1
            else:
                try:
                    shutil.move(str(src), str(dest))
                    if dest.name != target.name:
                        log(f"  이동: {src.relative_to(root)}  →  {dest.name} (이름변경)")
                    else:
                        log(f"  이동: {src.relative_to(root)}  →  {dest.name}")
                    moved += 1
                except Exception as e:
                    log(f"  [실패] {src}: {e}")
                    failed += 1
            done += 1
            progress(done, total, "이동 중")
        try:
            if not any(current.iterdir()):
                current.rmdir()
                log(f"  폴더 삭제: {current.relative_to(root)}")
        except Exception as e:
            log(f"  [폴더 삭제 실패] {current}: {e}")

    log(f"[펼치기 완료] 이동 {moved}개 / 건너뛰기 {skipped}개 / 실패 {failed}개")


# ---------- feature 2: translate via claude CLI ----------

def call_claude(prompt: str, claude_path: str, model: str, log) -> str | None:
    """Run `claude -p --model <model>` with prompt via stdin. Returns stdout or None."""
    try:
        if IS_WINDOWS:
            # On Windows the Claude CLI is typically a .cmd shim → need shell=True
            cmd = f'"{claude_path}" -p --model {model}'
            result = subprocess.run(
                cmd, shell=True, input=prompt,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=180, creationflags=NO_WINDOW,
            )
        else:
            result = subprocess.run(
                [claude_path, "-p", "--model", model], input=prompt,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=180,
            )
    except FileNotFoundError:
        log(f"  [오류] claude CLI를 찾을 수 없습니다: {claude_path}")
        return None
    except subprocess.TimeoutExpired:
        log("  [오류] claude CLI 호출 시간 초과")
        return None
    except Exception as e:
        log(f"  [오류] claude CLI 호출 실패: {e}")
        return None

    if result.returncode != 0:
        err = (result.stderr or "").strip()[-300:]
        log(f"  [오류] claude CLI 종료 코드 {result.returncode}: {err}")
        return None
    return (result.stdout or "").strip()


def call_gemma4(prompt: str, url: str, temperature: float, repeat_penalty: float,
                max_tokens: int, log) -> str | None:
    """POST to a koboldcpp / OpenAI-compatible /v1/chat/completions endpoint."""
    body = {
        "model": "local",
        "temperature": temperature,
        "repeat_penalty": repeat_penalty,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": (
                    "당신은 일본어 파일/폴더 이름을 한국어로 번역하는 도우미입니다. "
                    "사용자의 지시에 따라 반드시 JSON 형식으로만 응답합니다."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        log(f"  [오류] gemma4 서버 연결 실패 ({url}): {e}")
        return None
    except Exception as e:
        log(f"  [오류] gemma4 호출 실패: {e}")
        return None

    try:
        choice = payload["choices"][0]
        content = (choice["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        log(f"  [오류] gemma4 응답 형식 오류: {e}")
        return None

    if choice.get("finish_reason") == "length":
        log(f"  [경고] 응답이 max_tokens({max_tokens})에 걸려 잘렸습니다. "
            "더 작은 배치로 재시도하거나 config.json의 gemma4_max_tokens를 늘리세요.")
    return content


def call_translation_engine(prompt: str, cfg: dict, log) -> str | None:
    """Dispatch to the active translation engine based on cfg['translate_engine']."""
    engine = cfg.get("translate_engine", "claude")
    if engine == "gemma4":
        return call_gemma4(
            prompt,
            cfg.get("gemma4_url", DEFAULT_CONFIG["gemma4_url"]),
            float(cfg.get("gemma4_temperature", DEFAULT_CONFIG["gemma4_temperature"])),
            float(cfg.get("gemma4_repeat_penalty", DEFAULT_CONFIG["gemma4_repeat_penalty"])),
            int(cfg.get("gemma4_max_tokens", DEFAULT_CONFIG["gemma4_max_tokens"])),
            log,
        )
    return call_claude(
        prompt,
        cfg.get("claude_path", DEFAULT_CONFIG["claude_path"]),
        cfg.get("claude_model", DEFAULT_CONFIG["claude_model"]),
        log,
    )


def translate_batch(items: list[str], cfg: dict, log) -> dict[str, str]:
    if not items:
        return {}
    numbered = "\n".join(f"{i + 1}. {name}" for i, name in enumerate(items))
    prompt = (
        "다음은 일본어가 포함된 파일/폴더 이름의 본체(확장자 제외) 목록입니다. "
        "각 항목을 자연스러운 한국어로 번역해 주세요. "
        "확장자(.txt, .mp3 등)는 절대 추가하지 말고, "
        "윈도우 파일명에 사용할 수 없는 문자(<>:\"/\\|?*)도 사용하지 마세요. "
        "응답은 반드시 아래 JSON 형식 한 가지로만 출력하세요. 설명, 코드블록 표시(```), 주석은 절대 포함하지 마세요.\n\n"
        '{"translations": ["번역결과1", "번역결과2", ...]}\n\n'
        f"항목 ({len(items)}개):\n{numbered}"
    )

    output = call_translation_engine(prompt, cfg, log)
    if not output:
        return {}

    start, endp = output.find("{"), output.rfind("}")
    if start < 0 or endp < 0:
        log(f"  [파싱 실패] JSON을 찾지 못함: {output[:200]}")
        return {}
    try:
        parsed = json.loads(output[start:endp + 1])
    except json.JSONDecodeError as e:
        log(f"  [파싱 실패] {e}: {output[start:endp + 1][:200]}")
        return {}

    translations = parsed.get("translations") or []
    if len(translations) != len(items):
        # Positional zip would misalign every item after a dropped one (wrong
        # names), so discard the whole batch and let translate_names() re-request
        # it in smaller chunks where alignment is reliable.
        log(f"  [경고] 번역 개수 불일치: 입력 {len(items)} / 출력 {len(translations)} — 재시도합니다")
        return {}
    return dict(zip(items, translations))


def translate_names(keys: list[str], cfg: dict, log, progress) -> dict[str, str]:
    """Translate every key, retrying any that come back missing or empty in
    progressively smaller batches.

    Local models often return a mismatched item count or unparseable JSON for a
    full batch, which drops entries silently — folder names included. Shrinking
    the batch on each retry (down to 1) makes the response reliable and recovers
    the dropped items instead of leaving them untranslated.
    """
    result: dict[str, str] = {}
    pending = list(dict.fromkeys(keys))
    batch_size = TRANSLATE_BATCH
    max_rounds = 4
    for round_no in range(1, max_rounds + 1):
        if not pending:
            break
        label = "번역 요청 중" if round_no == 1 else "미번역 재요청 중"
        if round_no > 1:
            log(f"  [재시도 {round_no - 1}] 미번역 {len(pending)}개 재요청 (배치 크기 {batch_size})")
        total_batches = (len(pending) + batch_size - 1) // batch_size
        progress(0, total_batches, label)
        for bi, i in enumerate(range(0, len(pending), batch_size)):
            batch = pending[i:i + batch_size]
            if round_no == 1:
                log(f"  요청: {i + 1}-{i + len(batch)} / {len(pending)}")
            for k, v in translate_batch(batch, cfg, log).items():
                if v and v.strip():
                    result[k] = v
            progress(bi + 1, total_batches, label)
        pending = [k for k in pending if k not in result]
        batch_size = max(1, batch_size // 2)

    if pending:
        preview = ", ".join(pending[:10]) + (" ..." if len(pending) > 10 else "")
        log(f"  [번역 안 됨] {len(pending)}개 항목을 끝내 번역하지 못했습니다: {preview}")
    return result


def _translate_key(p: Path) -> tuple[str, bool]:
    """Return (translation_key, is_stem).
    - Files where the stem has Japanese → translate only the stem; suffix is reattached after.
      This guarantees same-stem-different-suffix files share one translation result.
    - Folders, or files with Japanese only in the suffix → translate full name.
    """
    if not p.is_dir() and has_japanese(p.stem):
        return p.stem, True
    return p.name, False


def translate_folder(root: Path, recursive: bool, conflict_mode: str,
                     cfg: dict, log, progress) -> None:
    if not root.is_dir():
        log(f"[오류] {root}은(는) 폴더가 아닙니다.")
        return

    items: list[Path] = []
    if recursive:
        for cur, _subs, files in os.walk(root, topdown=False):
            curp = Path(cur)
            for f in files:
                if has_japanese(f):
                    items.append(curp / f)
            if curp != root and has_japanese(curp.name):
                items.append(curp)
    else:
        for entry in root.iterdir():
            if has_japanese(entry.name):
                items.append(entry)

    if not items:
        log("[번역] 일본어 이름이 포함된 항목이 없습니다.")
        return

    engine = cfg.get("translate_engine", "claude")
    log(f"[번역] {len(items)}개 항목 발견. (엔진: {engine})")

    # Dedup by translation key (stem for files w/ JP stem; full name otherwise).
    keys = [_translate_key(p)[0] for p in items]
    unique = list(dict.fromkeys(keys))
    name_map = translate_names(unique, cfg, log, progress)

    if not name_map:
        log("[번역 실패] 처리할 결과가 없습니다.")
        return

    progress(0, len(items), "이름 변경 중")
    renamed = skipped = failed = 0
    for idx, path in enumerate(items):
        key, is_stem = _translate_key(path)
        translated = name_map.get(key)
        if translated:
            cleaned = safe_filename(translated)
            # Reattach the original suffix when we translated only the stem.
            new_name = cleaned + path.suffix if is_stem else cleaned
            if new_name and new_name != path.name:
                target = path.parent / new_name
                dest = resolve_conflict(target, conflict_mode)
                if dest is None:
                    log(f"  건너뛰기: {path.name} → {new_name} (대상 존재)")
                    skipped += 1
                else:
                    try:
                        path.rename(dest)
                        log(f"  이름변경: {path.name}  →  {dest.name}")
                        renamed += 1
                    except Exception as e:
                        log(f"  [실패] {path}: {e}")
                        failed += 1
        else:
            log(f"  [번역 결과 없음] {path.name}")
        progress(idx + 1, len(items), "이름 변경 중")

    log(f"[번역 완료] 이름변경 {renamed}개 / 건너뛰기 {skipped}개 / 실패 {failed}개")


# ---------- feature 3: convert audio ----------

def convert_audio(root: Path, recursive: bool, conflict_mode: str,
                  ffmpeg_path: str, delete_original: bool, log, progress) -> None:
    if not root.is_dir():
        log(f"[오류] {root}은(는) 폴더가 아닙니다.")
        return

    targets: list[Path] = []
    if recursive:
        for cur, _subs, files in os.walk(root):
            for f in files:
                if f.lower().endswith((".wav", ".flac")):
                    targets.append(Path(cur) / f)
    else:
        for entry in root.iterdir():
            if entry.is_file() and entry.suffix.lower() in (".wav", ".flac"):
                targets.append(entry)

    if not targets:
        log("[변환] WAV/FLAC 파일이 없습니다.")
        return

    log(f"[변환] {len(targets)}개 파일 변환 시작...")
    progress(0, len(targets), "변환 중")
    converted = skipped = failed = 0

    for idx, src in enumerate(targets):
        target = src.with_suffix(".mp3")
        dest = resolve_conflict(target, conflict_mode)
        if dest is None:
            log(f"  건너뛰기: {src.name} (mp3 이미 존재)")
            skipped += 1
            progress(idx + 1, len(targets), "변환 중")
            continue
        cmd = [
            ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            "-codec:a", "libmp3lame", "-qscale:a", "2",
            str(dest),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=NO_WINDOW,
            )
        except FileNotFoundError:
            log(f"[오류] ffmpeg를 찾을 수 없습니다: {ffmpeg_path}")
            return
        except Exception as e:
            log(f"  [실패] {src.name}: {e}")
            failed += 1
            progress(idx + 1, len(targets), "변환 중")
            continue

        if result.returncode == 0:
            log(f"  변환: {src.name}  →  {dest.name}")
            converted += 1
            if delete_original:
                try:
                    src.unlink()
                    log(f"    원본 삭제: {src.name}")
                except Exception as e:
                    log(f"    [원본 삭제 실패] {e}")
        else:
            err = (result.stderr or "").strip()[-200:]
            log(f"  [변환 실패] {src.name}: {err}")
            failed += 1
        progress(idx + 1, len(targets), "변환 중")

    log(f"[변환 완료] 성공 {converted}개 / 건너뛰기 {skipped}개 / 실패 {failed}개")


# ---------- feature 4: fix subtitle names ----------

def strip_media_ext_from_subtitle(name: str) -> str | None:
    """'파일명.mp3.vtt' -> '파일명.vtt'. Returns the fixed name, or None if the
    name is not a subtitle carrying an embedded media extension."""
    p = Path(name)
    if p.suffix.lower() not in SUBTITLE_EXTS:
        return None
    inner = Path(p.stem)  # e.g. '파일명.mp3'
    if inner.suffix.lower() not in MEDIA_EXTS:
        return None
    fixed = inner.stem + p.suffix  # '파일명' + '.vtt'
    if not inner.stem or fixed == name:
        return None
    return fixed


def fix_subtitle_names(root: Path, recursive: bool, conflict_mode: str,
                       log, progress) -> None:
    if not root.is_dir():
        log(f"[오류] {root}은(는) 폴더가 아닙니다.")
        return

    targets: list[Path] = []
    if recursive:
        for cur, _subs, files in os.walk(root):
            for f in files:
                if strip_media_ext_from_subtitle(f):
                    targets.append(Path(cur) / f)
    else:
        for entry in root.iterdir():
            if entry.is_file() and strip_media_ext_from_subtitle(entry.name):
                targets.append(entry)

    if not targets:
        log("[자막] 고칠 자막 파일이 없습니다. (예: 이름.mp3.vtt)")
        return

    log(f"[자막] {len(targets)}개 자막 파일 발견.")
    progress(0, len(targets), "이름 변경 중")
    renamed = skipped = failed = 0

    for idx, src in enumerate(targets):
        new_name = strip_media_ext_from_subtitle(src.name)
        target = src.parent / new_name
        dest = resolve_conflict(target, conflict_mode)
        if dest is None:
            log(f"  건너뛰기: {src.name} → {new_name} (대상 존재)")
            skipped += 1
        else:
            try:
                src.rename(dest)
                log(f"  이름변경: {src.name}  →  {dest.name}")
                renamed += 1
            except Exception as e:
                log(f"  [실패] {src}: {e}")
                failed += 1
        progress(idx + 1, len(targets), "이름 변경 중")

    log(f"[자막 완료] 이름변경 {renamed}개 / 건너뛰기 {skipped}개 / 실패 {failed}개")


# ---------- GUI ----------

class App:
    def __init__(self, root: Tk):
        self.root = root
        self.cfg = load_config()
        self._busy = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.root.title("Joy4_Folder")
        self.root.geometry("860x980")
        self.root.minsize(700, 820)

        outer = Frame(self.root, padx=10, pady=10)
        outer.pack(fill=BOTH, expand=True)

        # --- common settings ---
        settings = ttk.LabelFrame(outer, text="공통 설정")
        settings.pack(fill=X, pady=(0, 8))

        Label(settings, text="이름 충돌 처리:").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        self.conflict_var = StringVar(value=self.cfg["conflict_mode"])
        for i, (val, lab) in enumerate([
            ("overwrite", "덮어쓰기"),
            ("rename", "숫자 붙이기"),
            ("skip", "건너뛰기"),
        ]):
            Radiobutton(
                settings, text=lab, variable=self.conflict_var, value=val,
                command=self._save_settings,
            ).grid(row=0, column=i + 1, sticky=W, padx=6)

        Label(settings, text="ffmpeg 경로:").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        self.ffmpeg_var = StringVar(value=self.cfg["ffmpeg_path"])
        e1 = Entry(settings, textvariable=self.ffmpeg_var)
        e1.grid(row=1, column=1, columnspan=3, sticky=W + E, padx=6)
        e1.bind("<FocusOut>", lambda _e: self._save_settings())

        Label(settings, text="claude CLI 경로:").grid(row=2, column=0, sticky=W, padx=6, pady=4)
        self.claude_var = StringVar(value=self.cfg["claude_path"])
        e2 = Entry(settings, textvariable=self.claude_var)
        e2.grid(row=2, column=1, columnspan=3, sticky=W + E, padx=6)
        e2.bind("<FocusOut>", lambda _e: self._save_settings())

        Label(settings, text="claude 모델:").grid(row=3, column=0, sticky=W, padx=6, pady=4)
        self.model_var = StringVar(value=self.cfg["claude_model"])
        e3 = Entry(settings, textvariable=self.model_var)
        e3.grid(row=3, column=1, columnspan=3, sticky=W + E, padx=6)
        e3.bind("<FocusOut>", lambda _e: self._save_settings())

        Label(settings, text="gemma4 URL:").grid(row=4, column=0, sticky=W, padx=6, pady=4)
        self.gemma4_url_var = StringVar(value=self.cfg["gemma4_url"])
        e4 = Entry(settings, textvariable=self.gemma4_url_var)
        e4.grid(row=4, column=1, columnspan=3, sticky=W + E, padx=6)
        e4.bind("<FocusOut>", lambda _e: self._save_settings())

        settings.columnconfigure(3, weight=1)

        # --- feature 1 ---
        f1 = ttk.LabelFrame(outer, text="1. 하위폴더 펼치기")
        f1.pack(fill=X, pady=4)
        self.flatten_path = StringVar()
        row1 = Frame(f1)
        row1.pack(fill=X, padx=6, pady=6)
        Entry(row1, textvariable=self.flatten_path).pack(side=LEFT, fill=X, expand=True)
        Button(row1, text="폴더 선택", command=lambda: self._pick(self.flatten_path)).pack(side=LEFT, padx=4)
        Button(row1, text="실행", command=self._run_flatten, width=8).pack(side=LEFT)

        # --- feature 2 ---
        f2 = ttk.LabelFrame(outer, text="2. 일본어 → 한국어 이름 번역")
        f2.pack(fill=X, pady=4)
        self.translate_path = StringVar()
        row2 = Frame(f2)
        row2.pack(fill=X, padx=6, pady=6)
        Entry(row2, textvariable=self.translate_path).pack(side=LEFT, fill=X, expand=True)
        Button(row2, text="폴더 선택", command=lambda: self._pick(self.translate_path)).pack(side=LEFT, padx=4)
        Button(row2, text="실행", command=self._run_translate, width=8).pack(side=LEFT)

        opts2 = Frame(f2)
        opts2.pack(fill=X, padx=6, pady=(0, 6))
        Label(opts2, text="엔진:").pack(side=LEFT)
        self.engine_var = StringVar(value=self.cfg.get("translate_engine", "claude"))
        Radiobutton(
            opts2, text="Claude (CLI)", variable=self.engine_var, value="claude",
            command=self._save_settings,
        ).pack(side=LEFT, padx=(4, 8))
        Radiobutton(
            opts2, text="Gemma4 (local)", variable=self.engine_var, value="gemma4",
            command=self._save_settings,
        ).pack(side=LEFT)
        self.translate_recursive = IntVar(value=int(self.cfg["recursive_translate"]))
        Checkbutton(
            opts2, text="하위 폴더까지 처리", variable=self.translate_recursive,
            command=self._save_settings,
        ).pack(side=LEFT, padx=(20, 0))

        # --- feature 3 ---
        f3 = ttk.LabelFrame(outer, text="3. WAV / FLAC → MP3 변환 (ffmpeg)")
        f3.pack(fill=X, pady=4)
        self.audio_path = StringVar()
        row3 = Frame(f3)
        row3.pack(fill=X, padx=6, pady=6)
        Entry(row3, textvariable=self.audio_path).pack(side=LEFT, fill=X, expand=True)
        Button(row3, text="폴더 선택", command=lambda: self._pick(self.audio_path)).pack(side=LEFT, padx=4)
        Button(row3, text="실행", command=self._run_convert, width=8).pack(side=LEFT)
        opts = Frame(f3)
        opts.pack(fill=X, padx=6, pady=(0, 6))
        self.audio_recursive = IntVar(value=int(self.cfg["recursive_convert"]))
        Checkbutton(
            opts, text="하위 폴더까지 처리", variable=self.audio_recursive,
            command=self._save_settings,
        ).pack(side=LEFT)
        self.delete_original = IntVar(value=int(self.cfg["delete_originals_after_convert"]))
        Checkbutton(
            opts, text="변환 후 원본 삭제", variable=self.delete_original,
            command=self._save_settings,
        ).pack(side=LEFT, padx=(20, 0))

        # --- feature 4 ---
        f4 = ttk.LabelFrame(outer, text="4. 자막 파일명 맞추기 (예: 이름.mp3.vtt → 이름.vtt)")
        f4.pack(fill=X, pady=4)
        self.subtitle_path = StringVar()
        row4 = Frame(f4)
        row4.pack(fill=X, padx=6, pady=6)
        Entry(row4, textvariable=self.subtitle_path).pack(side=LEFT, fill=X, expand=True)
        Button(row4, text="폴더 선택", command=lambda: self._pick(self.subtitle_path)).pack(side=LEFT, padx=4)
        Button(row4, text="실행", command=self._run_fix_subs, width=8).pack(side=LEFT)
        opts4 = Frame(f4)
        opts4.pack(fill=X, padx=6, pady=(0, 6))
        self.subtitle_recursive = IntVar(value=int(self.cfg["recursive_subtitle"]))
        Checkbutton(
            opts4, text="하위 폴더까지 처리", variable=self.subtitle_recursive,
            command=self._save_settings,
        ).pack(side=LEFT)

        # --- log ---
        logframe = ttk.LabelFrame(outer, text="로그")
        logframe.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.log_text = Text(logframe, height=14, wrap="word")
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        sb = Scrollbar(logframe, command=self.log_text.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.log_text.config(yscrollcommand=sb.set)

        progress_row = Frame(outer)
        progress_row.pack(fill=X, pady=(6, 0))
        self.progress_bar = ttk.Progressbar(progress_row, mode="determinate", length=400)
        self.progress_bar.pack(side=LEFT, fill=X, expand=True)
        self.progress_label_var = StringVar(value="")
        Label(progress_row, textvariable=self.progress_label_var, fg="#333", width=22, anchor="e").pack(side=LEFT, padx=(8, 0))

        bottom = Frame(outer)
        bottom.pack(fill=X, pady=(4, 0))
        Button(bottom, text="로그 지우기", command=lambda: self.log_text.delete("1.0", END)).pack(side=RIGHT)
        self.status_var = StringVar(value="준비됨")
        Label(bottom, textvariable=self.status_var, fg="#555").pack(side=LEFT)

    # --- helpers ---

    def _pick(self, var: StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    def _log(self, msg: str) -> None:
        self.root.after(0, lambda: (self.log_text.insert(END, msg + "\n"), self.log_text.see(END)))

    def _set_progress(self, current: int, total: int, label: str = "") -> None:
        def _update():
            if total <= 0:
                self.progress_bar["maximum"] = 1
                self.progress_bar["value"] = 0
                self.progress_label_var.set("")
            else:
                self.progress_bar["maximum"] = total
                self.progress_bar["value"] = current
                pct = int(current * 100 / total)
                prefix = f"{label} " if label else ""
                self.progress_label_var.set(f"{prefix}{current}/{total} ({pct}%)")
        self.root.after(0, _update)

    def _save_settings(self) -> None:
        self.cfg.update({
            "conflict_mode": self.conflict_var.get(),
            "ffmpeg_path": self.ffmpeg_var.get(),
            "claude_path": self.claude_var.get(),
            "claude_model": self.model_var.get(),
            "gemma4_url": self.gemma4_url_var.get(),
            "translate_engine": self.engine_var.get(),
            "recursive_translate": bool(self.translate_recursive.get()),
            "recursive_convert": bool(self.audio_recursive.get()),
            "recursive_subtitle": bool(self.subtitle_recursive.get()),
            "delete_originals_after_convert": bool(self.delete_original.get()),
        })
        save_config(self.cfg)

    def _run_threaded(self, label: str, fn) -> None:
        if self._busy:
            messagebox.showinfo("진행 중", "이미 다른 작업이 실행 중입니다. 끝나면 다시 시도하세요.")
            return
        self._busy = True
        self.status_var.set(f"{label} 실행 중...")

        def _wrap():
            try:
                fn()
            except Exception as e:
                self._log(f"[예상치 못한 오류] {e}")
            finally:
                self._busy = False
                self.root.after(0, lambda: self.status_var.set("준비됨"))
                self._set_progress(0, 0, "")

        threading.Thread(target=_wrap, daemon=True).start()

    # --- runners ---

    def _run_flatten(self) -> None:
        path = self.flatten_path.get().strip()
        if not path:
            messagebox.showwarning("경고", "폴더를 선택하세요.")
            return
        if not Path(path).is_dir():
            messagebox.showerror("오류", "유효한 폴더가 아닙니다.")
            return
        if not messagebox.askyesno(
            "확인",
            f"이 작업은 되돌릴 수 없습니다.\n\n{path}\n\n"
            "위 폴더의 모든 하위폴더 내용물을 최상위로 꺼내고\n"
            "비게 된 하위폴더를 삭제합니다. 계속할까요?",
        ):
            return
        self._save_settings()
        self._run_threaded("하위폴더 펼치기", lambda: flatten_folder(
            Path(path), self.conflict_var.get(), self._log, self._set_progress,
        ))

    def _run_translate(self) -> None:
        path = self.translate_path.get().strip()
        if not path:
            messagebox.showwarning("경고", "폴더를 선택하세요.")
            return
        if not Path(path).is_dir():
            messagebox.showerror("오류", "유효한 폴더가 아닙니다.")
            return
        self._save_settings()
        self._run_threaded("이름 번역", lambda: translate_folder(
            Path(path),
            bool(self.translate_recursive.get()),
            self.conflict_var.get(),
            self.cfg,
            self._log,
            self._set_progress,
        ))

    def _run_convert(self) -> None:
        path = self.audio_path.get().strip()
        if not path:
            messagebox.showwarning("경고", "폴더를 선택하세요.")
            return
        if not Path(path).is_dir():
            messagebox.showerror("오류", "유효한 폴더가 아닙니다.")
            return
        self._save_settings()
        self._run_threaded("오디오 변환", lambda: convert_audio(
            Path(path),
            bool(self.audio_recursive.get()),
            self.conflict_var.get(),
            self.ffmpeg_var.get(),
            bool(self.delete_original.get()),
            self._log,
            self._set_progress,
        ))

    def _run_fix_subs(self) -> None:
        path = self.subtitle_path.get().strip()
        if not path:
            messagebox.showwarning("경고", "폴더를 선택하세요.")
            return
        if not Path(path).is_dir():
            messagebox.showerror("오류", "유효한 폴더가 아닙니다.")
            return
        self._save_settings()
        self._run_threaded("자막 파일명 맞추기", lambda: fix_subtitle_names(
            Path(path),
            bool(self.subtitle_recursive.get()),
            self.conflict_var.get(),
            self._log,
            self._set_progress,
        ))


def main() -> None:
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
