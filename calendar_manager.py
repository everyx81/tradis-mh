"""
JARVIS MK3 일정 & 메모 관리 모듈
- LocalScheduleManager: 로컬 JSON 기반 일정/메모 CRUD
- WindowsNotifier: Windows 토스트 알림
"""

import os
import sys
import json
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import threading
import time

# Windows 알림 - winotify 사용 (안정적인 네이티브 토스트)
try:
    from winotify import Notification, audio
    TOAST_AVAILABLE = True
except ImportError:
    TOAST_AVAILABLE = False
    print("[경고] winotify 패키지가 없습니다. pip install winotify")


class WindowsNotifier:
    """Windows 토스트 알림 관리 (winotify 기반)"""
    
    def __init__(self):
        self.app_id = "TRADIS MH"
    
    def show_toast(self, title: str, message: str, duration: int = 10, icon_path: str = None):
        """토스트 알림 표시"""
        if not TOAST_AVAILABLE:
            print(f"[알림 불가] {title}: {message}")
            return False
        
        try:
            toast = Notification(
                app_id=self.app_id,
                title=title,
                msg=message,
                duration="short" if duration <= 5 else "long",
                icon=icon_path if icon_path else ""
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
            return True
        except Exception as e:
            print(f"[알림 오류] {e}")
            return False


class LocalScheduleManager:
    """로컬 JSON 파일 기반 일정 & 메모 관리"""
    
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(base_dir, 'data')
            
        os.makedirs(data_dir, exist_ok=True)
        
        self.data_file = os.path.join(data_dir, "schedules.json")
        self.notifier = WindowsNotifier()
        self._reminder_thread = None
        self._stop_reminder = threading.Event()
        self._data_changed = threading.Event() # [NEW] 데이터 변경 감지용 이벤트
        self._ui_callbacks = []  # UI 갱신 콜백 리스트
        self._cached_data = None  # [PERF] 메모리 캐시 (디스크 I/O 감소)
        self._cache_lock = threading.Lock()

        # 데이터 파일 초기화
        self._ensure_data_file()
    
    def _ensure_data_file(self):
        """데이터 파일이 없으면 생성"""
        if not os.path.exists(self.data_file):
            self._save_data({"schedules": [], "memos": []})
    
    def _load_data(self) -> Dict:
        """데이터 파일 로드 (메모리 캐시 우선, 변경 시만 디스크 읽기)"""
        with self._cache_lock:
            if self._cached_data is not None:
                return self._cached_data
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "memos" not in data:
                    data["memos"] = []

                is_modified = False
                for schedule in data.get("schedules", []):
                    # 마이그레이션 로직 (이전 속성을 새로운 구조로 변환)
                    if "alerts" not in schedule:
                        old_val = schedule.pop("remind_minutes_list", None)
                        if old_val is None:
                            old_val = schedule.pop("remind_minutes", [60])
                        schedule["alerts"] = old_val if isinstance(old_val, list) else [old_val]
                        is_modified = True

                    if "reminded_alerts" not in schedule:
                        schedule["reminded_alerts"] = schedule.pop("reminded_at", [])
                        is_modified = True

                    if "snooze_until" not in schedule:
                        schedule["snooze_until"] = None
                        is_modified = True

                if is_modified:
                    self._save_data(data)

                with self._cache_lock:
                    self._cached_data = data
                return data
        except Exception as e:
            print(f"[데이터 로드 오류] {e}")
            return {"schedules": [], "memos": []}
    
    def _save_data(self, data: Dict) -> bool:
        """데이터 파일 저장 + 메모리 캐시 동시 갱신"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            with self._cache_lock:
                self._cached_data = data
            return True
        except Exception as e:
            print(f"[데이터 저장 오류] {e}")
            return False
            
    def _trigger_update(self):
        """데이터 변경 시 캐시 무효화 + 대기 중인 스레드를 깨움"""
        with self._cache_lock:
            self._cached_data = None
        self._data_changed.set()

    def register_ui_callback(self, callback):
        """UI 갱신 콜백 등록 (스누즈/완료/반복 등 데이터 변경 시 호출됨)"""
        self._ui_callbacks.append(callback)

    def _notify_ui(self):
        """등록된 UI 콜백 호출"""
        for cb in self._ui_callbacks:
            try:
                cb()
            except Exception as e:
                print(f"[UI callback error] {e}")
    
    # ========== 일정 관리 ==========
    
    def list_schedules(self, include_completed: bool = False) -> List[Dict]:
        """일정 목록 조회 (날짜순 정렬)"""
        data = self._load_data()
        schedules = data.get("schedules", [])
        
        if not include_completed:
            schedules = [s for s in schedules if not s.get("completed", False)]
        
        # 날짜순 정렬
        schedules.sort(key=lambda x: x.get("datetime", ""))
        return schedules
    
    def add_schedule(self, title: str, dt: datetime, note: str = "", alerts: list = None, repeat: str = "None") -> Dict:
        """일정 추가 (alerts: [0, 15, 60, ...] 대상시간으로부터 몇 분 전에 알릴 것인지의 리스트)"""
        if alerts is None:
            alerts = [0]  # 기본값: 정각
        
        data = self._load_data()
        
        schedule = {
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "datetime": dt.isoformat(),
            "note": note,
            "alerts": alerts,
            "reminded_alerts": [],
            "snooze_until": None,
            "repeat": repeat,
            "completed": False,
            "created_at": datetime.now().isoformat()
        }
        
        data["schedules"].append(schedule)
        if self._save_data(data):
            self._trigger_update() # 스레드 깨우기
        return schedule
    
    def update_schedule(self, schedule_id: str, **kwargs) -> Optional[Dict]:
        """일정 수정"""
        data = self._load_data()
        
        for schedule in data["schedules"]:
            if schedule["id"] == schedule_id:
                for key, value in kwargs.items():
                    if key in schedule:
                        if key == "datetime" and isinstance(value, datetime):
                            schedule[key] = value.isoformat()
                            schedule["reminded_alerts"] = []
                            schedule["snooze_until"] = None
                        else:
                            schedule[key] = value
                if self._save_data(data):
                    self._trigger_update()
                    self._notify_ui()
                return schedule
        return None
    
    def delete_schedule(self, schedule_id: str) -> bool:
        """일정 삭제"""
        data = self._load_data()
        original_count = len(data["schedules"])
        data["schedules"] = [s for s in data["schedules"] if s["id"] != schedule_id]
        
        if len(data["schedules"]) < original_count:
            if self._save_data(data):
                self._trigger_update()
            return True
        return False
    
    def complete_schedule(self, schedule_id: str) -> bool:
        """일정 완료 처리"""
        return self.update_schedule(schedule_id, completed=True) is not None
        
    def snooze_schedule(self, schedule_id: str, minutes: int = 15) -> bool:
        """[NEW] Snooze: 일정을 n분 뒤로 강제 연기 (알림기록은 유지, 스누즈 타이머만 세팅)"""
        data = self._load_data()
        for schedule in data["schedules"]:
            if schedule["id"] == schedule_id:
                now = datetime.now()
                new_snooze = now + timedelta(minutes=minutes)
                schedule["snooze_until"] = new_snooze.isoformat()

                if self._save_data(data):
                    self._trigger_update()
                    self._notify_ui()
                return True
        return False
    
    # ========== 메모 관리 ==========
    
    def list_memos(self) -> List[Dict]:
        """메모 목록 조회 (최신순)"""
        data = self._load_data()
        memos = data.get("memos", [])
        memos.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return memos
    
    def add_memo(self, title: str, content: str = "") -> Dict:
        """메모 추가"""
        data = self._load_data()
        
        memo = {
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "content": content,
            "locked": False,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        data["memos"].append(memo)
        self._save_data(data)
        return memo
    
    def update_memo(self, memo_id: str, **kwargs) -> Optional[Dict]:
        """메모 수정"""
        data = self._load_data()
        
        for memo in data["memos"]:
            if memo["id"] == memo_id:
                for key, value in kwargs.items():
                    if key in ["title", "content", "locked"]:
                        memo[key] = value
                memo["updated_at"] = datetime.now().isoformat()
                self._save_data(data)
                return memo
        return None
    
    def delete_memo(self, memo_id: str) -> bool:
        """메모 삭제 (잠긴 메모는 삭제 불가)"""
        data = self._load_data()
        # 잠긴 메모 삭제 방지
        for m in data["memos"]:
            if m["id"] == memo_id and m.get("locked", False):
                return False
        original_count = len(data["memos"])
        data["memos"] = [m for m in data["memos"] if m["id"] != memo_id]
        
        if len(data["memos"]) < original_count:
            self._save_data(data)
            return True
        return False
    
    # ========== 알림 관리 ==========
    
    def check_reminders(self) -> List[Dict]:
        """알림 시간이 된 일정 확인 및 알림 발송 (다중 알림, 스누즈 지원)"""
        now = datetime.now()
        data = self._load_data()
        triggered = []
        is_modified = False
        
        for schedule in data.get("schedules", []):
            if schedule.get("completed"):
                continue
            
            try:
                schedule_dt = datetime.fromisoformat(schedule["datetime"])
                title = schedule.get("title", "")
                
                # 1. 스누즈 확인 (가장 높은 우선순위)
                snooze_until_str = schedule.get("snooze_until")
                is_snoozed_trigger = False
                
                if snooze_until_str:
                    snooze_dt = datetime.fromisoformat(snooze_until_str)
                    if now >= snooze_dt:
                        is_snoozed_trigger = True
                        schedule["snooze_until"] = None  # 스누즈 해제
                        is_modified = True
                
                # 2. 일반 알람 확인
                alerts = schedule.get("alerts", [0])
                reminded_alerts = schedule.get("reminded_alerts", [])
                
                triggered_min = None
                
                if is_snoozed_trigger:
                    triggered_min = "snooze"
                else:
                    # 시간이 짧은 알람(가장 최근/현재에 가까운 것)부터 검사
                    for remind_min in sorted(alerts): 
                        if remind_min in reminded_alerts:
                            continue
                        
                        remind_time = schedule_dt - timedelta(minutes=remind_min)
                        if now >= remind_time:
                            # 팝업에 표시할 대표 알람은 가장 최근 시점(가장 작은 분)것으로 유지
                            if triggered_min is None:
                                triggered_min = remind_min
                            # 지나간 긴 시간(n일 전) 알람들도 모두 발송 처리됨으로써 불필요한 연속 팝업 방지
                            reminded_alerts.append(remind_min)
                            schedule["reminded_alerts"] = reminded_alerts
                            is_modified = True
                            
                # 3. 알림 발송 처리
                if triggered_min is not None:
                    if triggered_min == "snooze":
                        toast_title = f"⏰ [다시 알림] {title}"
                        msg = "스누즈한 일정 시간입니다!"
                    elif triggered_min == 0:
                        toast_title = f"🔔 지금! {title}"
                        msg = "일정 기한(시간)이 정각에 돌입했습니다!"
                    else:
                        if triggered_min >= 1440:
                            toast_title = f"⏰ {triggered_min // 1440}일 전 알림"
                        elif triggered_min >= 60:
                            toast_title = f"⏰ {triggered_min // 60}시간 전 알림"
                        else:
                            toast_title = f"⏰ {triggered_min}분 전 알림"
                        msg = f"📋 예정 기한: {schedule_dt.strftime('%m/%d %H:%M')}\n{title}"
                    
                    try:
                        from gui.jarvis_toast import show_custom_toast
                        show_custom_toast(
                            title=toast_title,
                            message=msg,
                            is_sticky=True,
                            snooze_callback=lambda minutes, sid=schedule["id"]: self.snooze_schedule(sid, minutes),
                            complete_callback=lambda sid=schedule["id"]: self.complete_schedule(sid)
                        )
                    except Exception as e:
                        print(f"[알림 팝업 오류] {e}")
                        self.notifier.show_toast(toast_title, msg, duration=10)
                        
                    triggered.append(schedule)
                
                # 4. 반복 처리 (기한이 완전히 지난 경우)
                if now >= schedule_dt:
                    # 반복 설정이 되어 있다면
                    repeat = schedule.get("repeat", "None")
                    if repeat != "None":
                        next_dt = schedule_dt
                        
                        if repeat == "Every30Min": delta = timedelta(minutes=30)
                        elif repeat == "Hourly": delta = timedelta(hours=1)
                        elif repeat == "Every3Hours": delta = timedelta(hours=3)
                        elif repeat == "Daily": delta = timedelta(days=1)
                        elif repeat == "Weekly": delta = timedelta(weeks=1)
                        elif repeat == "Monthly": delta = timedelta(days=30)
                        else: delta = timedelta(days=1)
                        
                        while next_dt <= now:
                            next_dt += delta
                            
                        schedule["datetime"] = next_dt.isoformat()
                        schedule["reminded_alerts"] = []
                        schedule["snooze_until"] = None
                        is_modified = True

                        try:
                            from gui.jarvis_toast import show_custom_toast
                            show_custom_toast(
                                title="⏰ 다음 일정 반복 예약됨",
                                message=f"📅 {title}\n{next_dt.strftime('%m/%d')} {next_dt.strftime('%H:%M')}",
                                duration=5
                            )
                        except Exception:
                            self.notifier.show_toast(
                                "⏰ 다음 일정 반복 예약됨",
                                f"📅 {next_dt.strftime('%m/%d')} {next_dt.strftime('%H:%M')}",
                                duration=5
                            )
                        
            except Exception as e:
                print(f"[알림 확인 오류] {e}")
                
        if is_modified:
            self._save_data(data)
            self._notify_ui()

        return triggered

    def _get_next_reminder_time(self) -> Optional[datetime]:
        """가장 가까운 다음 알림 시간 계산"""
        now = datetime.now()
        next_times = []
        
        data = self._load_data()
        for schedule in data.get("schedules", []):
            if schedule.get("completed"):
                continue
            
            try:
                # 스누즈가 있다면 그게 1순위 타겟
                snooze_str = schedule.get("snooze_until")
                if snooze_str:
                    snooze_dt = datetime.fromisoformat(snooze_str)
                    if snooze_dt <= now:
                        return now
                    next_times.append(snooze_dt)
                    continue
                
                schedule_dt = datetime.fromisoformat(schedule["datetime"])
                alerts = schedule.get("alerts", [0])
                reminded_alerts = schedule.get("reminded_alerts", [])
                
                for remind_min in alerts:
                    if remind_min in reminded_alerts:
                        continue
                        
                    remind_time = schedule_dt - timedelta(minutes=remind_min)
                    if remind_time <= now:
                        return now
                    
                    next_times.append(remind_time)
            except Exception as e:
                print(f"[다음 알림 계산 오류] {e}")
                
        if next_times:
            return min(next_times)
        return None
    
    def start_reminder_loop(self, interval_seconds: int = 60):
        """백그라운드 알림 체크 루프 시작 (Smart Wake-up 방식)"""
        if self._reminder_thread and self._reminder_thread.is_alive():
            return  # 이미 실행 중
        
        self._stop_reminder.clear()
        self._data_changed.clear()
        
        def loop():
            print("[ScheduleManager] Smart Wake-up Loop Started.")
            while not self._stop_reminder.is_set():
                try:
                    # 1. 다음 알림 시간 계산
                    next_time = self._get_next_reminder_time()
                    
                    wait_seconds = interval_seconds # 기본 대기 시간
                    
                    if next_time:
                        now = datetime.now()
                        diff = (next_time - now).total_seconds()
                        # CPU 100% 점유를 막기 위해 최소 1.0초 대기 강제
                        wait_seconds = max(1.0, diff) 
                        # print(f"[Smart Wait] Next alert in {wait_seconds:.1f}s")
                    
                    # 2. 스마트 대기 (지정된 시간까지 Sleep 하다가, 데이터 변경 시 즉시 기상)
                    # wait()가 True를 반환하면 set()이 호출된 것 (데이터 변경됨)
                    # False를 반환하면 Timeout (알림 시간 도달)
                    data_changed = self._data_changed.wait(timeout=wait_seconds)
                    
                    if data_changed:
                        # 데이터가 변경되어 깨어남 -> 다시 계산하러 loop 처음으로
                        # print("[Smart Wait] Data changed! Waking up...")
                        self._data_changed.clear()
                        continue
                        
                    # 3. 타임아웃으로 깨어남 -> 알림 체크 수행
                    if not self._stop_reminder.is_set():
                        self.check_reminders()
                        
                except Exception as e:
                    print(f"[Loop Error] {e}")
                    time.sleep(5) # 에러 시 5초 대기로 폭주 방지 강화
        
        self._reminder_thread = threading.Thread(target=loop, daemon=True)
        self._reminder_thread.start()
    
    def stop_reminder_loop(self):
        """백그라운드 알림 체크 루프 중지"""
        self._stop_reminder.set()


# 테스트용
if __name__ == "__main__":
    manager = LocalScheduleManager()
    
    # 테스트 일정 추가
    schedule = manager.add_schedule(
        title="테스트 일정",
        dt=datetime.now() + timedelta(hours=1),
        note="테스트 메모",
        alerts=[30]
    )
    print(f"일정 추가: {schedule}")
    
    # 테스트 메모 추가
    memo = manager.add_memo(
        title="테스트 메모",
        content="이것은 테스트 메모입니다."
    )
    print(f"메모 추가: {memo}")
    
    # 목록 조회
    print(f"일정 목록: {manager.list_schedules()}")
    print(f"메모 목록: {manager.list_memos()}")
    
    # Windows 알림 테스트
    notifier = WindowsNotifier()
    notifier.show_toast("TRADIS MH 알림 테스트", "일정관리 모듈이 정상 작동합니다!")
