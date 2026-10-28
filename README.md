# 자막 지우개 (subtitle-remover)

샤오홍슈·더우인·인스타그램·틱톡 같은 짧은 영상에 박혀 있는 자막을 찾아서, 그 자리를 **배경으로 자연스럽게 메꿔 주는** 개인용 프로그램입니다. 블러나 모자이크로 가리는 게 아니라, 자막이 처음부터 없던 영상처럼 만드는 게 목표예요.

## 어떻게 동작하나요

1. **자막 찾기**: PP-OCRv6 텍스트 검출 모델로 프레임마다 글자 위치를 찾고, 시간 흐름에 따라 추적해요.
   - 화면에 고정된 글자(자막·제목·캡션)만 지우고, 카메라와 함께 움직이는 간판 같은 글자는 남겨요.
   - 자막이 서서히 나타나거나 사라지는 프레임까지 마스크를 조금 늘려서 잔상이 안 남게 해요.
2. **메꾸기**: 자막 주변만 잘라서 [ProPainter](https://github.com/sczhou/ProPainter)(비디오 인페인팅 AI)로 채워요.
   - 다른 프레임에서 보이는 **진짜 배경을 가져와서** 붙이고, 영상 내내 한 번도 안 보인 부분은 주변을 보고 그려요.
   - 장면이 바뀌는 곳(컷)은 따로 처리해서, 다른 장면의 배경이 섞이지 않게 해요.
3. **합치기**: 채운 부분만 원본 해상도 영상에 부드럽게 붙이고, 원래 소리를 그대로 넣어서 저장해요. 나머지 부분은 원본 그대로예요.

## Colab에서 쓰기 (추천)

노트북 컴퓨터에 그래픽카드가 없어도 돼요. 무료 Google Colab의 GPU에서 돌아가요.

### 처음 한 번만

**1) GitHub 토큰 만들기**: Colab이 이 비공개 저장소의 코드를 받아 갈 때 필요해요.

1. GitHub에 로그인 → 오른쪽 위 프로필 사진 → **Settings**
2. 왼쪽 메뉴 맨 아래 **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
3. 다음처럼 입력해요.
   - Token name: `colab`
   - Expiration: 원하는 기간 (만료되면 새로 만들어서 3)번처럼 다시 저장하면 돼요)
   - Repository access: **Only select repositories** → `subtitle-remover`
   - Permissions → Repository permissions → **Contents: Read-only**
4. **Generate token**을 누르고 `github_pat_`로 시작하는 토큰을 복사해요. 창을 닫으면 다시 볼 수 없어요.

**2) 노트북 열기**

- [colab.research.google.com](https://colab.research.google.com)에서 **파일 → 노트북 열기 → GitHub 탭**을 눌러요.
- **비공개 저장소 포함**에 체크하고 GitHub 접근을 허용해요.
- `purewater5221-dotcom/subtitle-remover`를 고르고 `colab/subtitle_remover.ipynb`를 열어요.
- 열린 노트북을 **파일 → Drive에 사본 저장**해 두면, 다음부터는 내 Drive에서 바로 열 수 있어요.

**3) 토큰 저장**

노트북 왼쪽의 🔑(보안 비밀) → **새 보안 비밀 추가**를 눌러요. 이름은 `GITHUB_TOKEN`, 값에는 복사한 토큰을 붙여 넣고, **노트북 액세스**를 켜요.

**4) GPU 켜기**

메뉴 **런타임 → 런타임 유형 변경 → T4 GPU**를 선택해요.

### 매번

1. **①**을 실행해요. Google Drive 연결 창이 뜨면 허용해요.
2. 내 Google Drive의 `subtitle-remover/input` 폴더에 영상을 넣어요. PC에서 [drive.google.com](https://drive.google.com)에 끌어다 놓으면 돼요.
3. **②**에서 설정을 고르고 **③**을 실행해요.
4. **④**로 원본과 결과를 나란히 비교해요. 결과는 `subtitle-remover/output/원래이름_clean.mp4`로 저장돼요.

### 설정 설명

| 설정 | 설명 |
|---|---|
| 무엇을 할까요? | **자막 지우기**, 또는 **마스크만 확인**. 마스크만 확인은 지울 부분을 표시한 미리보기만 빠르게 만들어요. |
| 품질 | 빠르게 / 보통 / 최고. 최고로 갈수록 느리지만 더 자연스러워요. |
| 어디에 있는 글자를 지울까요? | 전체 화면, 아래쪽 절반 같은 영역을 고르거나 비율 좌표로 직접 입력해요. 영역 밖의 글자는 건드리지 않아요. |
| 어떤 글자를 지울까요? | **화면에 고정된 자막·글자만**(권장), 또는 **간판 등 모든 글자** |

마스크 미리보기 색깔의 의미예요.

- 🟥 빨간 부분: 지울 곳
- 🟨 노란 테두리: 찾았지만 남긴 글자
- 🟦 파란 상자: 처리 영역
- ⬜ 흰 테두리: 장면이 바뀌는 프레임

### 잘 안 될 때

- **GPU가 없다고 나와요**: 메뉴 *런타임 → 런타임 유형 변경 → T4 GPU*를 고르세요. 무료 GPU를 못 받는 시간대도 있으니 잠시 뒤 다시 해 보세요.
- **GPU 메모리가 부족하대요**: 품질을 *빠르게*로 낮추세요.
- **자막이 덜 지워져요**: *마스크만 확인*으로 빨간 부분이 자막을 다 덮는지 보세요.
  - 자막에 노란 테두리가 있으면 "찾았지만 남긴 글자"라는 뜻이에요. 대상을 *모든 글자*로 바꾸거나 영역을 지정하세요.
- **지우면 안 되는 글자까지 지워져요**: 영역을 *아래쪽 1/3* 등으로 좁히세요.
- **세션이 끊겼어요**: ①부터 다시 실행하세요. 이미 끝난 영상은 건너뛰어요.

### 알아둘 점

- 자막 뒤 배경이 영상 내내 한 번도 안 보이면(카메라가 고정된 경우) AI가 추측해서 그려요. 그래서 원본과 똑같지는 않고, 복잡한 무늬·얼굴·손이 지나가면 살짝 뭉개질 수 있어요.
- 카메라가 고정된 장면의 간판 글자는 자막과 구분이 안 돼서 같이 지워질 수 있어요. 이럴 땐 영역을 지정하세요.
- 틱톡·더우인 로고 같은 그림은 글자가 아니라서 지워지지 않아요. 아이디 글자는 지워질 수 있어요.
- HDR 영상(아이폰 HDR 등)은 SDR로 저장돼서 색이 조금 달라질 수 있어요.

## 명령어로 쓰기 (고급)

FFmpeg가 설치돼 있어야 해요. GPU가 없으면 ProPainter가 매우 느려요.

```bash
pip install -r requirements.txt
python -m subtitle_remover 영상.mp4                    # → 영상_clean.mp4
python -m subtitle_remover 폴더/ -o 결과폴더/            # 폴더 안의 영상 전부
python -m subtitle_remover 영상.mp4 --detect-only      # 마스크 미리보기만 (영상_clean_mask.mp4)
python -m subtitle_remover 영상.mp4 --region bottom --quality best
python -m subtitle_remover 영상.mp4 --method opencv    # 빠른 테스트용 (품질 낮음)
python -m subtitle_remover --help                      # 모든 옵션
```

## 폴더 구조

```
subtitle_remover/
  video_io.py      FFmpeg로 영상 읽기/쓰기 (프레임 정확, 소리 유지)
  detect.py        텍스트 검출 (PP-OCRv6, ONNX)
  tracking.py      글자 추적, 자막/간판 구분, 프레임별 마스크 일정
  scenes.py        장면 전환(컷) 찾기
  planner.py       잘라서 처리할 영역과 구간 정하기
  masks.py         마스크 그리기, 경계 부드럽게
  inpaint/         메꾸기 엔진 (propainter, opencv)
  pipeline.py      전체 흐름 (찾기 → 메꾸기 → 합치기)
  cli.py           명령어
colab/             Colab 노트북 (tools/build_notebook.py로 생성)
tools/             합성 테스트 영상 만들기, 품질 측정, 노트북 생성
tests/             자동 테스트 (pytest)
samples/           테스트용 영상을 올리는 곳
```

## 개발 메모

- 테스트: `pytest`
- 정답이 있는 합성 테스트 영상 만들기: `python tools/make_synthetic.py 출력폴더 --motion pan`
- 품질 측정: `python tools/evaluate.py 결과.mp4 정답.mp4 정답_gt.npz --subtitled 입력.mp4`
- 노트북 수정: `tools/build_notebook.py`를 고친 뒤 실행하면 `colab/subtitle_remover.ipynb`가 다시 만들어져요.

## 사용한 모델과 라이선스

- **ProPainter** (ICCV 2023): [NTU S-Lab License 1.0](https://github.com/sczhou/ProPainter/blob/main/LICENSE). **비상업적 용도로만** 쓸 수 있어요. 코드는 처음 실행할 때 원본 저장소에서 받아 와요.
- **PP-OCRv6 텍스트 검출 모델**: [RapidOCR](https://github.com/RapidAI/RapidOCR) 패키지에 들어 있는 모델(Apache-2.0)을 써요.
- 이 저장소는 개인용이에요.
