import os
import json
import boto3
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import queue
import threading

class AWSConfigManager:
    def __init__(self):
        self.config_dir = os.path.join(os.path.expanduser("."), ".settings/.aws_camera_settings")
        self.config_file = os.path.join(self.config_dir, "config.json")
        self.history_file = os.path.join(self.config_dir, "history.json")
        self.current_user = 'USER'  # 현재 사용자 설정

        # 설정 디렉토리 생성
        os.makedirs(self.config_dir, exist_ok=True)

    def save_settings(self, settings):
        """현재 설정을 저장하고 히스토리에 추가"""
        try:
            # 전체 설정 저장
            with open(self.config_file, 'w') as f:
                json.dump(settings, f, indent=2)

            # 히스토리 기록 (민감 정보 제외)
            history = self.load_history()

            history_entry = {
                'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'user': self.current_user,
                'settings': {
                    'region': settings.get('region', ''),
                    'bucket': settings.get('bucket', ''),
                }
            }

            # 중복(같은 region/bucket) 히스토리 제거
            history = [h for h in history if not (
                h['settings']['region'] == history_entry['settings']['region'] and
                h['settings']['bucket'] == history_entry['settings']['bucket']
            )]

            history.append(history_entry)
            history = history[-10:]

            with open(self.history_file, 'w') as f:
                json.dump(history, f, indent=2)

            return True

        except Exception as e:
            print(f"설정 저장 실패: {str(e)}")
            return False

    def load_settings(self):
        """저장된 설정 로드"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"설정 로드 실패: {str(e)}")
        return {}

    def load_history(self):
        """설정 히스토리 로드"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"히스토리 로드 실패: {str(e)}")
        return []

class AWSSettingsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("AWS 설정")
        self.resizable(False, False)

        self.config_manager = AWSConfigManager()
        self.settings = self.config_manager.load_settings()

        # 업로드 활성화 변수 선언
        self.upload_enabled_var = tk.BooleanVar(
            value=self.settings.get('upload_enabled', False)
        )

        self._init_ui()
        self.center_window()
        self.add_history_button()

    def _init_ui(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill="both", expand=True)

        row = 0
        # AWS 자격증명 섹션
        ttk.Label(main_frame, text="AWS 자격증명", font=('Helvetica', 10, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 5))
        row += 1

        # S3 자동 업로드 체크박스
        ttk.Label(main_frame, text="S3 자동 업로드").grid(row=row, column=0, sticky="e")
        s3_upload_cb = ttk.Checkbutton(
            main_frame,
            text="촬영 시 S3 자동 업로드",
            variable=self.upload_enabled_var
        )
        s3_upload_cb.grid(row=row, column=1, sticky="w")
        row += 1

        # AWS Access Key
        ttk.Label(main_frame, text="Access Key:").grid(row=row, column=0, sticky="e", pady=5)
        self.access_key_var = tk.StringVar(value=self.settings.get('access_key', ''))
        self.access_key_entry = ttk.Entry(main_frame, textvariable=self.access_key_var, width=40)
        self.access_key_entry.grid(row=row, column=1, padx=5)
        row += 1

        # AWS Secret Key
        ttk.Label(main_frame, text="Secret Key:").grid(row=row, column=0, sticky="e", pady=5)
        self.secret_key_var = tk.StringVar(value=self.settings.get('secret_key', ''))
        self.secret_key_entry = ttk.Entry(main_frame, textvariable=self.secret_key_var, width=40, show="*")
        self.secret_key_entry.grid(row=row, column=1, padx=5)

        # Show/Hide Secret Key
        self.show_secret = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_frame, text="보이기", variable=self.show_secret,
                        command=self._toggle_secret_visibility).grid(row=row, column=2)
        row += 1

        # AWS Region
        ttk.Label(main_frame, text="Region:").grid(row=row, column=0, sticky="e", pady=5)
        self.region_var = tk.StringVar(value=self.settings.get('region', 'ap-northeast-2'))
        regions = ['ap-northeast-2', 'ap-northeast-1', 'us-east-1', 'us-west-1', 'eu-west-1']
        self.region_combo = ttk.Combobox(main_frame, textvariable=self.region_var, values=regions)
        self.region_combo.grid(row=row, column=1, sticky="ew", padx=5)
        row += 1

        # S3 Bucket
        ttk.Label(main_frame, text="Bucket:").grid(row=row, column=0, sticky="e", pady=5)
        self.bucket_var = tk.StringVar(value=self.settings.get('bucket', ''))
        self.bucket_entry = ttk.Entry(main_frame, textvariable=self.bucket_var, width=40)
        self.bucket_entry.grid(row=row, column=1, padx=5)
        row += 1

        # 버튼 프레임
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=10)

        ttk.Button(btn_frame, text="저장", command=self.save_settings).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="취소", command=self.destroy).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="연결 테스트", command=self.test_connection).pack(side="left", padx=5)

    def add_history_button(self):
        """히스토리 버튼 추가"""
        history_btn = ttk.Button(
            self,
            text="이전 설정 히스토리",
            command=self.show_history
        )
        history_btn.pack(pady=5, padx=10, anchor="e")

    def show_history(self):
        """설정 히스토리 창 표시"""
        history = self.config_manager.load_history()
        if not history:
            messagebox.showinfo("히스토리", "저장된 설정 히스토리가 없습니다.")
            return

        history_window = tk.Toplevel(self)
        history_window.title("설정 히스토리")
        history_window.geometry("500x400")

        # 히스토리 표시를 위한 트리뷰
        tree = ttk.Treeview(history_window, columns=('timestamp', 'user', 'settings'), show='headings')
        tree.heading('timestamp', text='날짜/시간')
        tree.heading('user', text='사용자')
        tree.heading('settings', text='설정')

        # 스크롤바 추가
        scrollbar = ttk.Scrollbar(history_window, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        # 트리뷰에 데이터 추가
        for entry in reversed(history):
            settings_str = f"Region: {entry['settings']['region']}, Bucket: {entry['settings']['bucket']}"
            tree.insert('', 'end', values=(
                entry['timestamp'],
                entry['user'],
                settings_str
            ))

        # 더블클릭 이벤트 처리
        def on_double_click(event):
            item = tree.selection()[0]
            selected_timestamp = tree.item(item)['values'][0]
            selected_entry = next(
                (entry for entry in history if entry['timestamp'] == selected_timestamp),
                None
            )
            if selected_entry:
                if messagebox.askyesno("설정 불러오기", "선택한 설정을 불러오시겠습니까?"):
                    self.load_history_entry(selected_entry)
                    history_window.destroy()

        tree.bind('<Double-1>', on_double_click)

        # 레이아웃
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 창 크기 조절 방지
        history_window.resizable(False, False)

        # 부모 창 중앙에 위치
        history_window.transient(self)
        history_window.grab_set()

    def load_history_entry(self, entry):
        """히스토리 항목 불러오기"""
        if 'settings' in entry:
            settings = entry['settings']
            if 'access_key' in settings:
                self.access_key_var.set(settings['access_key'])
            if 'region' in settings:
                self.region_var.set(settings['region'])
            if 'bucket' in settings:
                self.bucket_var.set(settings['bucket'])

    def _toggle_secret_visibility(self):
        """시크릿 키 보이기/숨기기 토글"""
        self.secret_key_entry.config(show="" if self.show_secret.get() else "*")

    def center_window(self):
        """창을 화면 중앙에 위치"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')

    def save_settings(self):
        settings = {
            'access_key': self.access_key_var.get().strip(),
            'secret_key': self.secret_key_var.get().strip(),
            'region': self.region_var.get().strip(),
            'bucket': self.bucket_var.get().strip(),
            'upload_enabled': self.upload_enabled_var.get()
        }

        if not all([settings['access_key'], settings['secret_key'],
                    settings['region'], settings['bucket']]):
            messagebox.showerror("입력 오류", "AWS 자격증명 정보를 모두 입력해주세요.")
            return

        try:
            if self.config_manager.save_settings(settings):
                messagebox.showinfo("성공", "설정이 저장되었습니다.")
                self.destroy()
            else:
                messagebox.showerror("저장 실패", "설정을 저장하는 중 오류가 발생했습니다.")
        except Exception as e:
            messagebox.showerror("저장 오류", f"설정을 저장하는 중 오류가 발생했습니다: {str(e)}")

    def test_connection(self):
        try:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=self.access_key_var.get().strip(),
                aws_secret_access_key=self.secret_key_var.get().strip(),
                region_name=self.region_var.get().strip()
            )
            bucket = self.bucket_var.get().strip()
            s3_client.head_bucket(Bucket=bucket)
            self.upload_enabled_var.set(True)
            messagebox.showinfo("성공", "AWS 연결 테스트 성공!\n자동 업로드가 활성화됩니다.")
        except Exception as e:
            self.upload_enabled_var.set(False)
            messagebox.showerror("연결 실패", f"AWS 연결 테스트 실패: {str(e)}\n자동 업로드가 비활성화됩니다.")

class AWSS3Manager:
    def __init__(self, log_callback=None):
        self.s3_client = None
        self.bucket_name = None
        self.log_callback = log_callback
        self.settings = {}
        self.upload_queue = queue.Queue()
        self.upload_thread = None
        self.stop_flag = threading.Event()
        self.initialize_client()
        self.start_upload_worker()

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)

    def load_settings(self):
        config_dir = os.path.join(os.path.expanduser("."), ".settings/.aws_camera_settings")
        config_file = os.path.join(config_dir, "config.json")
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    self.settings = json.load(f)
                return True
        except Exception as e:
            self.log(f"설정 로드 실패: {str(e)}")
        return False

    def initialize_client(self):
        if not self.load_settings():
            return False

        try:
            if all([self.settings.get('access_key'), self.settings.get('secret_key'),
                    self.settings.get('region'), self.settings.get('bucket')]):
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=self.settings['access_key'],
                    aws_secret_access_key=self.settings['secret_key'],
                    region_name=self.settings['region']
                )
                self.bucket_name = self.settings['bucket']
                self.log("S3 클라이언트 초기화 완료")
                return True
            else:
                self.s3_client = None
                self.log("설정 정보가 불완전합니다. S3 클라이언트 미초기화.")
                return False

        except Exception as e:
            self.log(f"S3 클라이언트 초기화 실패: {str(e)}")
            self.s3_client = None
            return False

    def manual_upload(self, image_path):
        if not self.s3_client:
            self.log("S3 클라이언트가 초기화되지 않았습니다.")
            return False

        try:
            filename = os.path.basename(image_path)
            today = datetime.now().strftime('%Y-%m')
            s3_key = f'photos/{today}/{filename}'
            self.s3_client.upload_file(
                image_path,
                self.bucket_name,
                s3_key,
                ExtraArgs={'ContentType': 'image/jpeg'}
            )
            self.log(f"수동 업로드 완료: {s3_key}")
            return True
        except Exception as e:
            self.log(f"수동 업로드 실패: {str(e)}")
            return False

    def start_upload_worker(self):
        if self.upload_thread is not None and self.upload_thread.is_alive():
            return

        self.stop_flag.clear()
        self.upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
        self.upload_thread.start()

    def stop_upload_worker(self):
        self.stop_flag.set()
        if self.upload_thread:
            self.upload_thread.join()

    def _upload_worker(self):
        while not self.stop_flag.is_set():
            try:
                image_path = self.upload_queue.get(timeout=1.0)
                self._process_upload(image_path)
                self.upload_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.log(f"업로드 작업자 오류: {str(e)}")
                continue

    def _process_upload(self, image_path):
        if not self.s3_client or not self.settings.get('upload_enabled', True):
            return

        try:
            filename = os.path.basename(image_path)
            today = datetime.now().strftime('%Y-%m')
            s3_key = f'photos/{today}/{filename}'
            self.s3_client.upload_file(
                image_path,
                self.bucket_name,
                s3_key,
                ExtraArgs={'ContentType': 'image/jpeg'}
            )
            self.log(f"자동 업로드 완료: {s3_key}")
        except Exception as e:
            self.log(f"파일 업로드 실패 ({image_path}): {str(e)}")

    def queue_upload(self, image_path):
        """이미지 업로드를 큐에 추가"""
        self.upload_queue.put(image_path)