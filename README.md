# Crypto Arbitrage Monitor

국내외 암호화폐 거래소 간 실시간 차익 거래 모니터링 대시보드

## 지원 거래소

| 거래소 | 타입 | 기준 통화 | 호가 | 입출금 상태 |
|--------|------|----------|------|------------|
| 빗썸 (Bithumb) | 국내 | KRW | WebSocket | 공개 API |
| 업비트 (Upbit) | 국내 | KRW | WebSocket | API Key 필요 |
| Binance | 해외 | USDT | WebSocket | API Key 필요 |
| Gate.io | 해외 | USDT | WebSocket | 공개 API |
| Bybit | 해외 | USDT | WebSocket | API Key 필요 |

## 주요 기능

- **실시간 호가 수집**: 5개 거래소 WebSocket 연결로 매수/매도 1호가 실시간 수신
- **스프레드 계산**: 거래소 간 가격 차이를 KRW 기준으로 자동 계산 (실시간 환율 적용)
- **입출금 상태 필터**: 입출금 불가 코인 자동 필터링 (토글 가능)
- **네트워크 정보**: 거래소별 지원 네트워크 표시 및 공통 네트워크 필터링
- **Gate.io 대출 조회**: 마진 대출 가능 코인 조회
- **알림 시스템**: 스프레드 기준 초과 시 브라우저 소리 알림 + 텔레그램 메시지
- **웹 대시보드**: 실시간 갱신되는 스프레드 순위 테이블

## 설치

### 요구사항
- Python 3.11 이상
- 인터넷 연결 (거래소 API 접근)

### 설치 방법

```bash
# 저장소 클론 또는 다운로드 후
cd crypto-arbitrage-monitor

# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정 (선택사항)
cp .env.example .env
# .env 파일을 편집하여 필요한 API 키 입력
```

## 실행

```bash
# 서버 시작
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# 또는
uvicorn main:app --host 0.0.0.0 --port 8000
```

브라우저에서 `http://localhost:8000` 접속

## 환경 변수 설정 (.env)

```env
# 텔레그램 알림 (선택사항)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# 거래소 API 키 (선택사항 - 입출금 상태 조회용)
UPBIT_ACCESS_KEY=your_key
UPBIT_SECRET_KEY=your_secret

BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret

BYBIT_API_KEY=your_key
BYBIT_API_SECRET=your_secret
```

> API 키 없이도 핵심 기능(호가 수집, 스프레드 계산, 알림)은 모두 동작합니다.
> API 키는 일부 거래소의 입출금 상태 조회에만 필요합니다.

## 대시보드 사용법

### 스프레드 테이블
- 코인별 매수/매도 거래소, 가격, 스프레드(%) 실시간 표시
- 스프레드 높은 순으로 정렬
- 코인 클릭 시 상세 정보(입출금 상태, 네트워크, Gate.io 대출) 표시

### 설정
- **Min Spread**: 최소 스프레드 기준 (기본 0.5%)
- **Deposit/Withdraw Filter**: 입출금 불가 코인 자동 제외
- **Common Network Filter**: 공통 네트워크 없는 쌍 제외

### 알림
- 스프레드 기준 초과 시 브라우저에서 소리 알림
- 텔레그램 봇 설정 시 메시지 자동 전송 (60초 쿨다운)

## 기술 스택

- **Backend**: Python 3.11+, FastAPI, asyncio, aiohttp
- **Frontend**: Vanilla JavaScript, SSE (Server-Sent Events)
- **실시간 통신**: WebSocket (거래소), SSE (브라우저)
- **설계 패턴**: Adapter Pattern (거래소 모듈화)

## 프로젝트 구조

```
crypto-arbitrage-monitor/
├── main.py                 # FastAPI 앱 진입점 + 라이프사이클
├── config.py               # 전역 설정
├── models.py               # Pydantic 데이터 모델
├── exchange_rate.py        # KRW/USDT 실시간 환율 관리
├── spread_engine.py        # 스프레드 계산 엔진
├── alert_manager.py        # 알림 시스템 (소리 + 텔레그램)
├── exchanges/
│   ├── base.py             # BaseExchange 추상 클래스
│   ├── bithumb.py          # 빗썸 어댑터
│   ├── upbit.py            # 업비트 어댑터
│   ├── binance.py          # Binance 어댑터
│   ├── gateio.py           # Gate.io 어댑터
│   └── bybit.py            # Bybit 어댑터
├── routers/
│   ├── stream.py           # SSE 스트림 엔드포인트
│   ├── api.py              # REST API
│   └── pages.py            # HTML 페이지 서빙
├── templates/
│   └── index.html          # 대시보드 HTML
├── static/
│   ├── css/style.css       # 스타일시트
│   ├── js/dashboard.js     # 대시보드 JavaScript
│   └── sounds/alert.mp3    # 알림 사운드
├── requirements.txt
├── .env.example
└── README.md
```
