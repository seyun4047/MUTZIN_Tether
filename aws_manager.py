import os
import queue
import threading
import requests
import json
import tkinter as tk
from tkinter import ttk, messagebox

# AWS 설정 파일 경로
AWS_CONFIG_PATH = os.path.join(os.path.expanduser("./"), ".settings/.aws_camera_settings", "config.json")


def load_aws_settings():
    """AWS 설정 로드"""
    if os.path.exists(AWS_CONFIG_PATH):
        try:
            with open(AWS_CONFIG_PATH, "r", encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        "lambda_url": "",
        "upload_enabled": True
    }


def save_aws_settings(settings):
    """AWS 설정 저장"""
    config_dir = os.path.dirname(AWS_CONFIG_PATH)
    os.makedirs(config_dir, exist_ok=True)
    with open(AWS_CONFIG_PATH, "w", encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


class AWSSettingsWindow(tk.Toplevel):
    """AWS 설정 창"""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("AWS S3 설정")
        self.geometry("600x300")
        self.resizable(False, False)

        # 현재 설정 로드
        self.settings = load_aws_settings()

        self._create_widgets()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill="both", expand=True)

        # Lambda URL 설정
        ttk.Label(main_frame, text="Lambda API URL:", font=("Arial", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 5)
        )
        ttk.Label(main_frame, text="(Presigned URL 발급용 Lambda Function URL)",
                  foreground="gray").grid(row=1, column=0, sticky="w", pady=(0, 10))

        self.lambda_url_var = tk.StringVar(value=self.settings.get("lambda_url", ""))
        lambda_entry = ttk.Entry(main_frame, textvariable=self.lambda_url_var, width=70)
        lambda_entry.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        # 예시 URL
        ttk.Label(main_frame, text="예시: https://xxxxx.lambda-url.ap-northeast-2.on.aws/",
                  foreground="blue", font=("Arial", 9)).grid(row=3, column=0, sticky="w", pady=(0, 20))

        # 업로드 활성화 체크박스
        self.upload_enabled_var = tk.BooleanVar(value=self.settings.get("upload_enabled", True))
        upload_cb = ttk.Checkbutton(
            main_frame,
            text="촬영 시 S3 자동 업로드 활성화",
            variable=self.upload_enabled_var
        )
        upload_cb.grid(row=4, column=0, sticky="w", pady=(0, 20))

        # 버튼 프레임
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=5, column=0, sticky="ew")

        ttk.Button(btn_frame, text="저장", command=self._save_settings, width=15).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(btn_frame, text="테스트", command=self._test_connection, width=15).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(btn_frame, text="취소", command=self.destroy, width=15).pack(side="left")

        main_frame.columnconfigure(0, weight=1)

    def _save_settings(self):
        """설정 저장"""
        lambda_url = self.lambda_url_var.get().strip()

        if not lambda_url:
            messagebox.showwarning("입력 오류", "Lambda URL을 입력해주세요.")
            return

        settings = {
            "lambda_url": lambda_url,
            "upload_enabled": self.upload_enabled_var.get()
        }

        save_aws_settings(settings)
        messagebox.showinfo("저장 완료", "AWS 설정이 저장되었습니다.")
        self.destroy()

    def _test_connection(self):
        """Lambda 연결 테스트"""
        lambda_url = self.lambda_url_var.get().strip()

        if not lambda_url:
            messagebox.showwarning("입력 오류", "Lambda URL을 입력해주세요.")
            return

        try:
            # 테스트용 파일명으로 Presigned URL 요청
            payload = {"filename": "test_connection.jpg"}
            headers = {"Content-Type": "application/json"}

            response = requests.post(lambda_url, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data.get("presigned_url"):
                    print(data.get("presigned_url"))
                    messagebox.showinfo("연결 성공",
                                        "Lambda 연결에 성공했습니다!\n\n"
                                        "Presigned URL이 정상적으로 발급되었습니다.")
                else:
                    messagebox.showwarning("응답 오류",
                                           "Lambda 응답에 presigned_url이 없습니다.")
            else:
                messagebox.showerror("연결 실패",
                                     f"Lambda 응답 오류\n\n"
                                     f"Status Code: {response.status_code}\n"
                                     f"응답: {response.text}")
        except requests.exceptions.Timeout:
            messagebox.showerror("연결 실패", "Lambda 요청 타임아웃\n\n연결을 확인해주세요.")
        except Exception as e:
            messagebox.showerror("연결 실패", f"Lambda 연결 오류:\n\n{str(e)}")


class AWSS3Manager:
    """S3 업로드 매니저 (Presigned URL 방식)"""

    def __init__(self, log_callback=None):
        """
        log_callback: 로그 출력 콜백 함수
        """
        self.log_callback = log_callback
        self.settings = load_aws_settings()
        self.lambda_url = self.settings.get("lambda_url", "")
        self.upload_enabled = self.settings.get("upload_enabled", True)

        # 업로드 큐 및 워커 스레드
        self.upload_queue = queue.Queue()
        self.upload_thread = None
        self.stop_flag = threading.Event()

        if self.lambda_url:
            self.start_upload_worker()
            self.log(f"S3 Manager 초기화 완료 (업로드: {'활성화' if self.upload_enabled else '비활성화'})")
        else:
            self.log("S3 Manager: Lambda URL이 설정되지 않음")

    def log(self, msg):
        """로그 출력"""
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(f"[S3] {msg}")

    def reload_settings(self):
        """설정 다시 로드"""
        self.settings = load_aws_settings()
        self.lambda_url = self.settings.get("lambda_url", "")
        self.upload_enabled = self.settings.get("upload_enabled", True)

        # 워커 스레드 재시작
        if self.lambda_url and not (self.upload_thread and self.upload_thread.is_alive()):
            self.start_upload_worker()

        self.log(f"설정 다시 로드됨 (업로드: {'활성화' if self.upload_enabled else '비활성화'})")

    def get_presigned_url(self, filename):
        """Lambda로부터 Presigned URL 획득"""
        if not self.lambda_url:
            self.log("Lambda URL이 설정되지 않음")
            return None

        try:
            payload = {"filename": filename}
            headers = {"Content-Type": "application/json"}
            response = requests.post(
                self.lambda_url,
                json=payload,
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("presigned_url")
            else:
                self.log(f"Presigned URL 요청 실패 ({response.status_code})")
        except requests.exceptions.Timeout:
            self.log(f"Presigned URL 요청 타임아웃")
        except Exception as e:
            self.log(f"Presigned URL 요청 오류: {e}")
        return None

    def upload_file(self, image_path):
        """S3에 파일 업로드 (실제 업로드 수행)"""
        if not self.upload_enabled:
            self.log("업로드 비활성화됨")
            return False

        if not self.lambda_url:
            self.log("Lambda URL이 설정되지 않아 업로드 불가")
            return False

        filename = os.path.basename(image_path)

        # 1. Presigned URL 획득
        url = self.get_presigned_url(filename)
        if not url:
            self.log(f"업로드 실패: Presigned URL 획득 실패 - {filename}")
            return False

        # 2. S3에 업로드
        try:
            with open(image_path, "rb") as f:
                data = f.read()  # 파일 읽기

            headers = {"Content-Type": "image/jpeg"}
            resp = requests.put(url, data=data, headers=headers, timeout=60)

            if resp.status_code == 200 or resp.status_code == 201:
                self.log(f"✓ S3 업로드 성공: {filename}")
                return True
            else:
                self.log(f"✗ S3 업로드 실패 ({resp.status_code}): {filename}")
                self.log(f"  응답: {resp.text}")
                return False
        except requests.exceptions.Timeout:
            self.log(f"✗ S3 업로드 타임아웃: {filename}")
        except Exception as e:
            self.log(f"✗ S3 업로드 오류: {filename} - {e}")
        return False

    def queue_upload(self, image_path):
        """업로드 큐에 추가 (비동기)"""
        if self.upload_enabled and self.lambda_url:
            self.upload_queue.put(image_path)
            self.log(f"업로드 큐에 추가됨: {os.path.basename(image_path)}")

    def manual_upload(self, image_path):
        """즉시 업로드 (동기)"""
        if self.upload_enabled and self.lambda_url:
            return self.upload_file(image_path)
        return False

    def start_upload_worker(self):
        """업로드 워커 스레드 시작"""
        if self.upload_thread and self.upload_thread.is_alive():
            return
        self.stop_flag.clear()
        self.upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
        self.upload_thread.start()
        self.log("S3 업로드 워커 시작됨")

    def stop_upload_worker(self):
        """업로드 워커 스레드 종료"""
        self.log("S3 업로드 워커 종료 중...")
        self.stop_flag.set()
        if self.upload_thread:
            self.upload_thread.join(timeout=5)
        self.log("S3 업로드 워커 종료됨")

    def _upload_worker(self):
        """백그라운드 업로드 워커"""
        while not self.stop_flag.is_set():
            try:
                image_path = self.upload_queue.get(timeout=1)
                self.upload_file(image_path)
                self.upload_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.log(f"업로드 워커 오류: {e}")

    def get_queue_size(self):
        """대기 중인 업로드 수 반환"""
        return self.upload_queue.qsize()

    def initialize_client(self):
        """
        AWS 설정 로드 후 Presigned URL 기반 S3 업로드 매니저 초기화
        """
        # 1. 설정 로드
        self.settings = load_aws_settings()
        if not self.settings:
            self.log("설정 파일을 불러올 수 없습니다.")
            return False

        # 2. Lambda URL 및 업로드 활성화 확인
        self.lambda_url = self.settings.get("lambda_url", "")
        self.upload_enabled = self.settings.get("upload_enabled", True)

        if not self.lambda_url:
            self.log("Lambda URL이 설정되지 않아 S3 Manager 초기화 실패")
            return False

        # 3. 업로드 큐 및 워커 스레드 초기화
        self.upload_queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.start_upload_worker()

        self.log(f"S3 Manager 초기화 완료 (업로드: {'활성화' if self.upload_enabled else '비활성화'})")
        return True