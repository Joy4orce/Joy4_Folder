# Joy4_Folder

일본어 자료 폴더를 정리하기 위한 Windows용 tkinter GUI 유틸리티입니다. 세 가지 기능을 한 창에서 제공합니다.

1. **하위폴더 펼치기** — 선택한 폴더의 모든 하위폴더 내용물을 최상위로 꺼내고, 비게 된 하위폴더를 삭제합니다.
2. **일본어 → 한국어 이름 번역** — 일본어가 포함된 파일/폴더 이름을 자연스러운 한국어로 바꿉니다. 번역 엔진은 두 가지 중 선택할 수 있습니다.
   - `claude` — Claude CLI(`claude -p --model ...`)를 통해 번역
   - `gemma4` — 로컬 koboldcpp 등 OpenAI 호환 `/v1/chat/completions` 엔드포인트로 번역
3. **WAV / FLAC → MP3 변환** — ffmpeg(libmp3lame, `-qscale:a 2`)로 오디오를 변환합니다. 선택적으로 원본 삭제 가능.

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
| `translate_engine` | 번역 엔진: `claude` / `gemma4` | `claude` |
| `gemma4_url` | Gemma4(OpenAI 호환) 엔드포인트 | `http://localhost:5001/v1/chat/completions` |
| `gemma4_temperature` | Gemma4 temperature | `0.1` |
| `gemma4_repeat_penalty` | Gemma4 repeat penalty | `1.05` |

## 주의

- "하위폴더 펼치기"는 **되돌릴 수 없는** 파일 이동/폴더 삭제를 수행합니다. 실행 전 확인 대화상자가 표시됩니다.
- 번역·변환은 원본을 이름 변경하거나(번역) 새 파일을 생성합니다(변환). 중요한 자료는 미리 백업하세요.
