# Joy4_Folder

일본어 자료 폴더를 정리하기 위한 Windows용 tkinter GUI 유틸리티입니다. 다섯 가지 기능을 한 창에서 제공합니다.

1. **하위폴더 펼치기** — 선택한 폴더의 모든 하위폴더 내용물을 최상위로 꺼내고, 비게 된 하위폴더를 삭제합니다.
2. **일본어 → 한국어 이름 번역** — 일본어가 포함된 파일/폴더 이름을 자연스러운 한국어로 바꿉니다. 번역 엔진은 두 가지 중 선택할 수 있습니다.
   - `claude` — Claude CLI(`claude -p --model ...`)를 통해 번역
   - `gemma4` — 로컬 koboldcpp 등 OpenAI 호환 `/v1/chat/completions` 엔드포인트로 번역
3. **WAV / FLAC → MP3 변환** — ffmpeg(libmp3lame, `-qscale:a 2`)로 오디오를 변환합니다. 선택적으로 원본 삭제 가능.
4. **자막 파일명 맞추기** — `이름.mp3.vtt`처럼 미디어 확장자가 끼어든 자막 파일명에서 그 부분을 제거해(`이름.vtt`) 미디어 파일과 짝이 맞도록 합니다. 자막 확장자(`.vtt .srt .ass .ssa .smi .sub .lrc .sbv`) 앞에 미디어 확장자(`.mp3 .mp4 .mkv .flac` 등)가 붙은 경우만 처리하며, 그 외 이름은 건드리지 않습니다.
5. **중복 폴더 정리** — 하위 폴더들을 탐색해, **내용이 겹치는** 형제 폴더(같은 트랙의 다른 버전)를 찾아 불필요한 쪽을 **휴지통으로** 이동합니다. 판단 규칙:
   - `mp3` 폴더와 `wav` 폴더가 함께 있으면 `wav`를 삭제 (mp3 우선)
   - `있음/있는/포함/포함된/有/あり` 계열과 `없음/없는/제거/無/なし` 계열이 함께 있으면 `없음/제거` 쪽을 삭제 (예: `효과음 있음`/`효과음 없음`, `SE 있음`/`SE 없음`, `환경음 포함`/`SE 환경음 제거`)
   - 규칙으로 판단할 수 없는 중복은 팝업으로 띄워 삭제할 폴더를 직접 선택
   - "내용이 달라도 이름이 짝이면 확인" 옵션(`dedup_name_only`)을 켜면, 폴더 안의 파일이 서로 달라도 이름이 짝(`있음`/`없음`, `mp3`/`wav` 등 양쪽 마커가 모두 있는 경우)이면 자동 삭제 대신 **팝업으로 띄워** 직접 선택하게 합니다. 홍수처럼 뜨지 않도록 양쪽에 마커가 다 있을 때만 후보로 잡습니다.
   - **직접 규칙 추가**: "남길 폴더 이름"(`dedup_keep_markers`) / "삭제할 폴더 이름"(`dedup_delete_markers`) 칸에 폴더 이름에 포함될 문자열을 쉼표로 구분해 적으면 내장 규칙에 더해집니다. 예: 삭제할 폴더 이름에 `통상판, 미포함`을 적으면 그 문자열이 든 폴더가 삭제 후보가 되고, `특전`을 남길 폴더 이름에 적으면 해당 폴더는 절대 삭제되지 않습니다(내장 삭제 마커와 겹쳐도 '남길'이 우선).
   - **안전장치**: 자동 삭제는 내용이 실제로 겹치는 폴더에만 적용하고(내용이 다르면 팝업으로만), 삭제 전 확인 창을 거치며, 영구 삭제가 아니라 **휴지통**으로 이동하므로 복구할 수 있습니다.

공통 옵션으로 이름 충돌 처리 방식(덮어쓰기 / 숫자 붙이기 / 건너뛰기)과 하위 폴더 재귀 처리 여부를 지정할 수 있습니다.

## 요구 사항

- **Python 3.10+** (`str | None` 등 최신 타입 힌트 사용). tkinter 포함 표준 설치본이면 됩니다.
- **ffmpeg** — 오디오 변환 기능 사용 시. `config.json`의 `ffmpeg_path`로 실행 파일 경로를 지정할 수 있습니다(기본값 `ffmpeg`, PATH에 있으면 그대로 사용).
- **번역 기능 사용 시(택1)**
  - Claude CLI가 설치되어 PATH 또는 `claude_path`로 접근 가능해야 합니다.
  - 또는 로컬 Gemma4 서버(koboldcpp 등)가 `gemma4_url`에서 응답해야 합니다.

외부 pip 패키지 의존성은 없습니다. 표준 라이브러리(tkinter, urllib 등)만 사용합니다.

## 실행 방법

```bat
실행.bat
```

또는 직접:

```sh
pythonw Joy4_Folder.py
```

`실행.bat`은 콘솔 코드페이지를 UTF-8(65001)로 설정하고 콘솔 창 없이 `pythonw`로 GUI를 띄웁니다.

## 설정

설정은 `config.json`에 저장되며 GUI에서 값을 바꾸면 자동 저장됩니다. 이 파일은 개인 설정이므로 `.gitignore`로 커밋에서 제외됩니다. 새 환경에서는 `config.example.json`을 복사해 시작하세요.

```sh
copy config.example.json config.json
```

| 키 | 설명 | 기본값 |
|---|---|---|
| `conflict_mode` | 이름 충돌 처리: `overwrite` / `rename` / `skip` | `rename` |
| `ffmpeg_path` | ffmpeg 실행 파일 경로 | `ffmpeg` |
| `claude_path` | Claude CLI 경로 | `claude` |
| `claude_model` | Claude 모델 이름 | `claude-haiku-4-5` |
| `delete_originals_after_convert` | 변환 후 원본 삭제 | `false` |
| `recursive_translate` | 번역 시 하위 폴더까지 처리 | `false` |
| `recursive_convert` | 변환 시 하위 폴더까지 처리 | `false` |
| `recursive_subtitle` | 자막 파일명 맞추기 시 하위 폴더까지 처리 | `false` |
| `recursive_dedup` | 중복 폴더 정리 시 하위 폴더까지 탐색 | `true` |
| `dedup_name_only` | 내용이 달라도 이름이 짝이면 팝업으로 확인 | `true` |
| `dedup_keep_markers` | 남길 폴더 이름 규칙(문자열 목록). 이 문자열이 든 폴더는 삭제하지 않음 | `[]` |
| `dedup_delete_markers` | 삭제할 폴더 이름 규칙(문자열 목록). 이 문자열이 든 폴더를 삭제 후보로 | `[]` |
| `translate_engine` | 번역 엔진: `claude` / `gemma4` | `claude` |
| `gemma4_url` | Gemma4(OpenAI 호환) 엔드포인트 | `http://localhost:5001/v1/chat/completions` |
| `gemma4_temperature` | Gemma4 temperature | `0.1` |
| `gemma4_repeat_penalty` | Gemma4 repeat penalty | `1.05` |
| `gemma4_max_tokens` | Gemma4 요청당 최대 생성 토큰. 파일명이 길면 응답이 잘리므로 넉넉히 필요 | `4096` |

## 주의

- "하위폴더 펼치기"는 **되돌릴 수 없는** 파일 이동/폴더 삭제를 수행합니다. 실행 전 확인 대화상자가 표시됩니다.
- 번역·변환은 원본을 이름 변경하거나(번역) 새 파일을 생성합니다(변환). 중요한 자료는 미리 백업하세요.
- "중복 폴더 정리"는 폴더를 **휴지통으로** 이동하므로 복구할 수 있지만, 삭제 전 확인 창의 목록을 반드시 확인하세요. (휴지통 이동은 Windows 전용입니다.)
