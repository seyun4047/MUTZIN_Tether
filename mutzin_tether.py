import gphoto2 as gp
import os
import glob
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import time
from PIL import Image, ImageTk
from pose_estimator import *
import json
from aws_manager import AWSSettingsWindow, AWSS3Manager

AWS_CONFIG_PATH = os.path.join(os.path.expanduser("./"), ".settings/.aws_camera_settings", "config.json")

# --------- S3 --------------------
def load_aws_settings():
    if os.path.exists(AWS_CONFIG_PATH):
        with open(AWS_CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

def save_aws_settings(settings):
    config_dir = os.path.dirname(AWS_CONFIG_PATH)
    os.makedirs(config_dir, exist_ok=True)
    with open(AWS_CONFIG_PATH, "w") as f:
        json.dump(settings, f, indent=2)

# --------- CAMERA UTILS ----------
def list_cameras():
    context = gp.Context()
    abilities_list = gp.Camera.autodetect(context)
    return abilities_list

def get_camera_setting(camera, option):
    try:
        config = camera.get_config()
        child = config.get_child_by_name(option)
        return child.get_value()
    except Exception:
        return None

def set_camera_config_with_choices(camera, option, value):
    try:
        config = camera.get_config()
        child = config.get_child_by_name(option)
        choices = list(child.get_choices())
        if value not in choices:
            return False, f"잘못된 입력입니다! 설정 가능한 값 중에서 선택하세요: {choices}"
        child.set_value(value)
        camera.set_config(config)
        return True, f"{option}가 {value}(으)로 설정되었습니다."
    except Exception:
        return False, f"{option} 설정 실패"

def set_aperture(camera, value):
    for option in ["aperture", "f-number"]:
        ok, msg = set_camera_config_with_choices(camera, option, value)
        if ok:
            return ok, msg
    return False, "조리개(f-number, aperture) 둘 다 설정 실패: 카메라 또는 렌즈에서 원격조리개 설정이 지원되지 않을 수 있습니다."

def get_unique_filename(folder, base_filename, ext):
    n = 1
    candidate = f"{base_filename}{ext}"
    while os.path.exists(os.path.join(folder, candidate)):
        n += 1
        candidate = f"{base_filename}_{n}{ext}"
    return candidate

def download_file(camera, folder, name, save_path, base_filename, exts, log_func=None, camera_lock=None):
    ext = os.path.splitext(name)[1].lower()
    if ext not in exts:
        return None
    outname = get_unique_filename(save_path, base_filename, ext)
    camera_file = gp.CameraFile()
    if camera_lock:
        with camera_lock:
            camera.file_get(folder, name, gp.GP_FILE_TYPE_NORMAL, camera_file)
    else:
        camera.file_get(folder, name, gp.GP_FILE_TYPE_NORMAL, camera_file)
    target = os.path.join(save_path, outname)
    camera_file.save(target)
    if log_func:
        log_func(f"파일 다운로드 완료: {target}")
    return target

def event_listener(camera, get_save_dir, get_base_filename, get_save_format, notify_saved, log_func, camera_lock, stop_event):
    raw_exts = [".arw", ".raw", ".nef", ".cr2", ".cr3", ".orf", ".rw2", ".dng"]
    jpeg_exts = [".jpg", ".jpeg"]
    while not stop_event.is_set():
        try:
            with camera_lock:
                event_type, event_data = camera.wait_for_event(1000)
            if event_type == gp.GP_EVENT_FILE_ADDED:
                folder = event_data.folder
                name = event_data.name
                save_format = get_save_format()
                if save_format == "raw":
                    exts = raw_exts
                elif save_format == "jpeg":
                    exts = jpeg_exts
                else:
                    exts = raw_exts + jpeg_exts
                save_dir = get_save_dir()
                base_filename = get_base_filename()
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir, exist_ok=True)
                log_func(f"[바디 촬영 감지] 파일 생성됨: {folder}/{name}")
                path = download_file(camera, folder, name, save_dir, base_filename, exts, log_func, camera_lock=camera_lock)
                if path:
                    notify_saved(path)
        except gp.GPhoto2Error as e:
            if e.code in (-53, -110):
                log_func(f"이벤트 감시 오류(-53 or -110): {e}. 카메라 재초기화 시도")
                try:
                    with camera_lock:
                        camera.exit()
                        time.sleep(1)
                        camera.init()
                        time.sleep(1)
                except Exception as e2:
                    log_func(f"이벤트 감시 카메라 재초기화 실패: {e2}")
            else:
                log_func(f"이벤트 감시 오류: {e}")
            time.sleep(1)
        except Exception as e:
            log_func(f"이벤트 감시 오류: {e}")
            time.sleep(1)

# --------- GUI IMAGE PREVIEW ----------
class FastResizableImageCanvas(tk.Canvas):
    def __init__(self, master, get_rotation_callback, get_quality_callback, get_zoom_callback, **kwargs):
        super().__init__(master, highlightthickness=0, **kwargs)
        self.get_rotation = get_rotation_callback
        self.get_quality = get_quality_callback
        self.get_zoom = get_zoom_callback
        self.pil_image = None
        self.tk_image = None
        self.current_image_path = None
        self.width = 500
        self.height = 500
        self.last_preview_args = (None, None, None, None, None, None)
        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", self._on_click)
        self.bind("<MouseWheel>", self._on_mousewheel)  # Windows
        self.bind("<Button-4>", self._on_mousewheel)    # Linux scroll up
        self.bind("<Button-5>", self._on_mousewheel)    # Linux scroll down

        self._zoom_callback = None

    def set_zoom_callback(self, callback):
        self._zoom_callback = callback

    def _on_click(self, event):
        self.focus_set()

    def _on_mousewheel(self, event):
        if event.num == 4 or getattr(event, 'delta', 0) > 0:
            if self._zoom_callback:
                self._zoom_callback(zoom_in=True)
        elif event.num == 5 or getattr(event, 'delta', 0) < 0:
            if self._zoom_callback:
                self._zoom_callback(zoom_in=False)

    def set_image(self, image_path):
        try:
            pil_img = Image.open(image_path)
            self.pil_image = pil_img
            self.current_image_path = image_path
            self._update_preview(force=True)
        except Exception as e:
            self.delete("all")
            self.create_text(10, 10, anchor="nw", text="이미지 열기 오류", fill="red")

    def _on_resize(self, event):
        self.width = event.width
        self.height = event.height
        self._update_preview()

    def _update_preview(self, force=False):
        if not self.pil_image:
            self.delete("all")
            self.create_text(10, 10, anchor="nw", text="(여기에 사진이 나타납니다)", fill="#666")
            return
        rot = self.get_rotation() or 0
        qual = self.get_quality() or 1.0
        zoom = self.get_zoom() or 1.0
        if (not force and
            self.current_image_path == self.last_preview_args[0] and
            rot == self.last_preview_args[1] and
            qual == self.last_preview_args[2] and
            zoom == self.last_preview_args[3] and
            (self.width, self.height) == self.last_preview_args[4:6]):
            return
        img = self.pil_image.copy()
        if rot != 0:
            img = img.rotate(-rot, expand=True)
        scale = qual
        if scale < 1.0:
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), resample=Image.BILINEAR)
        if zoom != 1.0:
            img = img.resize((max(1, int(img.width * zoom)), max(1, int(img.height * zoom))), resample=Image.BILINEAR)
        img.thumbnail((self.width, self.height), resample=Image.BILINEAR)
        self.tk_image = ImageTk.PhotoImage(img)
        self.delete("all")
        self.create_image(self.width // 2, self.height // 2, image=self.tk_image, anchor="center")
        self.last_preview_args = (self.current_image_path, rot, qual, zoom, self.width, self.height)

    def refresh_rotation_or_quality(self, force=False):
        self._update_preview(force=force)

class ThumbnailGallery(ttk.Frame):
    def __init__(self, master, on_thumbnail_click, thumb_size=56, **kwargs):
        super().__init__(master, **kwargs)
        self.on_thumbnail_click = on_thumbnail_click
        self.thumb_size = thumb_size
        self.thumbnails = []
        self.row_frame = ttk.Frame(self)
        self.row_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.row_frame, height=thumb_size+10, bg="#f8f8f8", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar = ttk.Scrollbar(self.row_frame, orient="horizontal", command=self.canvas.xview)
        self.scrollbar.pack(side="bottom", fill="x")
        self.canvas.configure(xscrollcommand=self.scrollbar.set)
        self.inner_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")
        self.inner_frame.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_inner_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas.find_all()[0], width=event.width)

    def add_thumbnail(self, image_path):
        try:
            pil_img = Image.open(image_path)
            pil_img.thumbnail((self.thumb_size, self.thumb_size))
            tk_img = ImageTk.PhotoImage(pil_img)
            btn = tk.Button(self.inner_frame, image=tk_img, width=self.thumb_size, height=self.thumb_size, command=lambda p=image_path: self.on_thumbnail_click(p))
            btn.image = tk_img
            btn.pack(side="left", padx=4, pady=2)
            self.thumbnails.append((image_path, tk_img, btn))
        except Exception:
            pass

    def clear(self):
        for _, _, btn in self.thumbnails:
            btn.destroy()
        self.thumbnails.clear()

class CameraGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Sony Camera Tether GUI")
        self.camera = None
        self.event_thread = None
        self.event_stop = threading.Event()
        self.camera_lock = threading.Lock()
        self.jpeg_quality = 1.0
        self.jpeg_history = []
        self.main_rotation_map = {}
        self.compare_rotation_map = {}
        self.main_zoom_map = {}
        self.compare_zoom_map = {}
        self.compare_path = None
        self.default_main_rotation = 0
        self.default_main_zoom = 1.0

        self.compare_layout_var = tk.StringVar(value="right")

        self.paned = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        self.paned.pack(fill="both", expand=True)
        self.pose_estimator = None
        self.pose_estimation_enabled = tk.BooleanVar(value=False)
        self.pose_estimation_in_progress = False
        self.pose_estimation_thread = None
        # -----------------------------


        # AWS S3 설정 메뉴 추가
        self.menubar = tk.Menu(root)
        root.config(menu=self.menubar)

        settings_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="설정", menu=settings_menu)
        settings_menu.add_command(label="AWS 설정", command=self.show_aws_settings)

        # S3 자동 업로드 설정 변수
        self.s3_upload_var = tk.BooleanVar(value=True)  # 기본값 True
        # -----------------------------

        param_frame = ttk.Frame(self.paned)
        self.paned.add(param_frame, weight=0)
        self.preview_pane = None
        self._init_preview_pane()
        self.paned.add(self.preview_pane, weight=1)

        # GUI에 pose estimation 컨트롤 추가
        self._init_param_frame(param_frame)
        # AWS S3 매니저 초기화
        self.s3_manager = AWSS3Manager(log_callback=self.log)

        # 썸네일 갱신 이벤트 연결
        self.save_dir_var.trace_add("write", lambda *a: self.refresh_thumbnails())
        self.base_filename_var.trace_add("write", lambda *a: self.refresh_thumbnails())

        self.connect_camera()
        self.refresh_thumbnails()
        self.poll_camera_settings()

    def _init_preview_pane(self):
        if self.preview_pane is not None:
            self.preview_pane.destroy()
        if self.compare_layout_var.get() == "below":
            self.preview_pane = ttk.Panedwindow(self.root, orient=tk.VERTICAL)
        else:
            self.preview_pane = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)

        self.main_canvas = FastResizableImageCanvas(
            self.preview_pane,
            get_rotation_callback=self.get_main_rotation,
            get_quality_callback=lambda: self.jpeg_quality,
            get_zoom_callback=self.get_main_zoom,
            bg="white"
        )
        self.compare_canvas = FastResizableImageCanvas(
            self.preview_pane,
            get_rotation_callback=self.get_compare_rotation,
            get_quality_callback=lambda: self.jpeg_quality,
            get_zoom_callback=self.get_compare_zoom,
            bg="#f6f7fa"
        )
        self.main_canvas.set_zoom_callback(self._main_zoom)
        self.compare_canvas.set_zoom_callback(self._compare_zoom)
        self.preview_pane.add(self.main_canvas, weight=4)
        self.preview_pane.add(self.compare_canvas, weight=4)
        self.thumb_gallery = ThumbnailGallery(self.preview_pane, self.on_thumbnail_click, thumb_size=64)
        self.preview_pane.add(self.thumb_gallery, weight=0)
        self._add_rotate_buttons()

    def show_aws_settings(self):
        aws_settings = AWSSettingsWindow(self.root)
        aws_settings.transient(self.root)
        aws_settings.grab_set()
        self.root.wait_window(aws_settings)
        # 설정 변경 후 S3 매니저 재초기화
        self.s3_manager.initialize_client()

    def show_jpeg_preview(self, image_path):
        self.refresh_thumbnails()
        # 중복 방지(새 파일만 추가)
        if image_path not in self.jpeg_history:
            self.jpeg_history.insert(0, image_path)
            self.thumb_gallery.add_thumbnail(image_path)
        if len(self.jpeg_history) > 1 and self.compare_path is None:
            self.compare_path = self.jpeg_history[1]
            self.compare_canvas.set_image(self.compare_path)
        path = image_path
        if path not in self.main_rotation_map:
            self.main_rotation_map[path] = self.default_main_rotation
        if path not in self.main_zoom_map:
            self.main_zoom_map[path] = self.default_main_zoom
        self.main_canvas.set_image(image_path)
        self.main_canvas.refresh_rotation_or_quality(force=True)
        if self.pose_estimation_enabled.get() and not self.pose_estimation_in_progress:
            import threading
            self.pose_estimation_thread = threading.Thread(
                target=self._estimate_pose,
                args=(image_path,),
                daemon=True
            )
            self.pose_estimation_thread.start()

    def _add_pose_estimation_controls(self, row, param_frame):
        # row = len(param_frame.grid_slaves()) // 4  # 기존 위젯 다음 행
        ttk.Separator(param_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=4, sticky="ew", pady=6
        )
        row += 1
        # Pose estimation 활성화 체크박스
        ttk.Label(param_frame, text="자세 추정:").grid(row=row, column=0, sticky="e")
        self.pose_enable_cb = ttk.Checkbutton(
            param_frame,
            # text="자세 추정 활성화",
            variable=self.pose_estimation_enabled,
            command=self._toggle_pose_estimation
        )
        self.pose_enable_cb.grid(row=row, column=1, columnspan=2, sticky="w")

        # 상태 표시 레이블
        self.pose_status_label = ttk.Label(param_frame, text="비활성화됨")
        self.pose_status_label.grid(row=row+2, column=2, columnspan=2, sticky="w")

    def _toggle_pose_estimation(self):
        if self.pose_estimation_enabled.get():
            from pose_estimator import PoseEstimator
            self.pose_estimator = PoseEstimator()
            self.pose_status_label.config(text="활성화됨")
        else:
            self.pose_estimator = None
            self.pose_status_label.config(text="비활성화됨")

    def _save_pose_estimation(self, image_path, results):
        """자세 추정 결과를 JSON 파일로 저장"""
        save_dir = os.path.dirname(image_path)
        base_name = os.path.basename(image_path)
        json_file = os.path.join(save_dir, "pose_estimation.json")

        # 새로운 결과 데이터 생성
        new_entry = {
            "filename": base_name,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "pose": results['pose'],
            "view": results['view'],
            "full_body": results['full_body'],
        }

        # 기존 JSON 파일 읽기 또는 새로 생성
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"pose_estimations": []}

        # 새 데이터 추가
        data["pose_estimations"].append(new_entry)

        # JSON 파일 저장
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        # 로그에 결과 표시
        formatted_result = self.pose_estimator.get_formatted_result(results)
        self.log(f"[Pose Estimation] {base_name}: {formatted_result}")

    def _estimate_pose(self, image_path):
        """별도 스레드에서 자세 추정을 수행"""
        if not self.pose_estimator or not self.pose_estimation_enabled.get():
            return

        self.pose_estimation_in_progress = True
        self.pose_status_label.config(text="Estimating pose...")

        try:
            results = self.pose_estimator.estimate(image_path)
            self._save_pose_estimation(image_path, results)
            self.root.after(0, lambda: self.pose_status_label.config(text="Pose estimation complete"))
        except Exception as e:
            self.root.after(0, lambda: self.pose_status_label.config(text=f"Pose estimation failed: {str(e)}"))
        finally:
            self.pose_estimation_in_progress = False
            self.root.after(3000, lambda: self.pose_status_label.config(text="Enabled"))
    def update_compare_layout(self):
        self.paned.forget(self.preview_pane)
        self._init_preview_pane()
        self.paned.add(self.preview_pane, weight=1)
        self.refresh_thumbnails()

    def _add_rotate_buttons(self):
        for frame in getattr(self, 'rotate_frames', []): frame.destroy()
        self.rotate_frames = []
        self.main_rotate_frame = self._make_rotate_buttons(self.main_canvas, which="main")
        self.compare_rotate_frame = self._make_rotate_buttons(self.compare_canvas, which="compare")
        self.rotate_frames = [self.main_rotate_frame, self.compare_rotate_frame]
        if self.compare_layout_var.get() == "right":
            self.main_rotate_frame.place(relx=0.5, rely=1.0, anchor="s", y=-7)
            self.compare_rotate_frame.place(relx=0.5, rely=1.0, anchor="s", y=-7)
        else:
            self.main_rotate_frame.place(relx=0.5, rely=1.0, anchor="s", y=-7)
            self.compare_rotate_frame.place(relx=0.5, rely=1.0, anchor="s", y=-7)

    def _init_param_frame(self, param_frame):
        row = 0
        self.camera_status = ttk.Label(param_frame, text="카메라 검색 중...", font=("Arial", 11, "bold"))
        self.camera_status.grid(row=row, column=0, columnspan=4, sticky="w")
        row += 1
        self.reload_btn = ttk.Button(param_frame, text="카메라 새로고침", command=self.connect_camera)
        self.reload_btn.grid(row=row, column=0, sticky="w", pady=(0,8))
        row += 1
        self._add_pose_estimation_controls(row, param_frame)
        row += 1
        row += 1
        ttk.Separator(param_frame, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", pady=6)
        row += 1
        ttk.Label(param_frame, text="ISO:").grid(row=row, column=0, sticky="e")
        self.iso_var = tk.StringVar()
        self.iso_lbl = ttk.Label(param_frame, textvariable=self.iso_var)
        self.iso_lbl.grid(row=row, column=1, sticky="w")
        self.iso_btn = ttk.Button(param_frame, text="설정 변경", command=self.set_iso)
        self.iso_btn.grid(row=row, column=2, sticky="w")
        row += 1

        ttk.Label(param_frame, text="셔터속도:").grid(row=row, column=0, sticky="e")
        self.ss_var = tk.StringVar()
        self.ss_lbl = ttk.Label(param_frame, textvariable=self.ss_var)
        self.ss_lbl.grid(row=row, column=1, sticky="w")
        self.ss_btn = ttk.Button(param_frame, text="설정 변경", command=self.set_ss)
        self.ss_btn.grid(row=row, column=2, sticky="w")
        row += 1

        ttk.Label(param_frame, text="조리개:").grid(row=row, column=0, sticky="e")
        self.ap_var = tk.StringVar()
        self.ap_lbl = ttk.Label(param_frame, textvariable=self.ap_var)
        self.ap_lbl.grid(row=row, column=1, sticky="w")
        self.ap_btn = ttk.Button(param_frame, text="설정 변경", command=self.set_ap)
        self.ap_btn.grid(row=row, column=2, sticky="w")
        row += 1

        ttk.Label(param_frame, text="화이트밸런스:").grid(row=row, column=0, sticky="e")
        self.wb_var = tk.StringVar()
        self.wb_lbl = ttk.Label(param_frame, textvariable=self.wb_var)
        self.wb_lbl.grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Label(param_frame, text="켈빈값:").grid(row=row, column=0, sticky="e")
        self.kelvin_var = tk.StringVar()
        self.kelvin_lbl = ttk.Label(param_frame, textvariable=self.kelvin_var)
        self.kelvin_lbl.grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Separator(param_frame, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", pady=6)
        row += 1
        ttk.Label(param_frame, text="미리보기 화질:").grid(row=row, column=0, sticky="e")
        self.quality_var = tk.DoubleVar(value=1.0)
        self.quality_slider = ttk.Scale(param_frame, from_=0.1, to=1.0, orient="horizontal", variable=self.quality_var, command=self._on_quality_slider)
        self.quality_slider.grid(row=row, column=1, columnspan=2, sticky="ew")
        ttk.Label(param_frame, text="저").grid(row=row, column=3, sticky="w")
        ttk.Label(param_frame, text="고").grid(row=row, column=4, sticky="w")
        row += 1
        ttk.Label(param_frame, text="비교 프레임 위치:").grid(row=row, column=0, sticky="e")
        ttk.Radiobutton(param_frame, text="오른쪽", variable=self.compare_layout_var, value="right", command=self.update_compare_layout).grid(row=row, column=1, sticky="w")
        ttk.Radiobutton(param_frame, text="아래쪽", variable=self.compare_layout_var, value="below", command=self.update_compare_layout).grid(row=row, column=2, sticky="w")
        row += 1
        ttk.Label(param_frame, text="저장 포맷:").grid(row=row, column=0, sticky="e")
        self.save_format_var = tk.StringVar(value="both")
        self.both_radio = ttk.Radiobutton(param_frame, text="RAW+JPEG", variable=self.save_format_var, value="both")
        self.both_radio.grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Label(param_frame, text="저장폴더:").grid(row=row, column=0, sticky="e")
        self.save_dir_var = tk.StringVar(value="./photos")
        self.save_dir_entry = ttk.Entry(param_frame, textvariable=self.save_dir_var, width=30)
        self.save_dir_entry.grid(row=row, column=1, sticky="w")
        self.dir_btn = ttk.Button(param_frame, text="폴더 선택", command=self.select_dir)
        self.dir_btn.grid(row=row, column=2, sticky="w")
        row += 1
        ttk.Label(param_frame, text="파일이름:").grid(row=row, column=0, sticky="e")
        self.base_filename_var = tk.StringVar(value="img")
        self.base_filename_entry = ttk.Entry(param_frame, textvariable=self.base_filename_var, width=20)
        self.base_filename_entry.grid(row=row, column=1, sticky="w")
        row += 1
        self.capture_btn = ttk.Button(param_frame, text="촬영 및 저장(PC에서)", command=self.capture)
        self.capture_btn.grid(row=row, column=0, columnspan=4, pady=12, sticky="ew")
        row += 1
        ttk.Label(param_frame, text="이벤트 로그:").grid(row=row, column=0, sticky="w")
        self.log_text = tk.Text(param_frame, height=7, width=50, state="disabled", wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=row+1, column=0, columnspan=5, sticky="ew", pady=(0, 10))

    def _on_quality_slider(self, val):
        self.jpeg_quality = float(val)
        self.main_canvas.refresh_rotation_or_quality(force=True)
        self.compare_canvas.refresh_rotation_or_quality(force=True)

    def get_main_rotation(self):
        path = self.jpeg_history[0] if self.jpeg_history else None
        if path in self.main_rotation_map:
            return self.main_rotation_map.get(path, 0)
        else:
            return self.default_main_rotation

    def get_compare_rotation(self):
        path = self.compare_path
        return self.compare_rotation_map.get(path, 0) if path else 0

    def set_main_rotation(self, deg):
        self.default_main_rotation = deg
        path = self.jpeg_history[0] if self.jpeg_history else None
        if path:
            self.main_rotation_map[path] = deg
            self.main_canvas.refresh_rotation_or_quality(force=True)

    def set_compare_rotation(self, deg):
        path = self.compare_path
        if path:
            self.compare_rotation_map[path] = deg
            self.compare_canvas.refresh_rotation_or_quality(force=True)

    def get_main_zoom(self):
        path = self.jpeg_history[0] if self.jpeg_history else None
        if path in self.main_zoom_map:
            return self.main_zoom_map.get(path, 1.0)
        else:
            return self.default_main_zoom

    def get_compare_zoom(self):
        path = self.compare_path
        return self.compare_zoom_map.get(path, 1.0) if path else 1.0

    def _main_zoom(self, zoom_in=True):
        path = self.jpeg_history[0] if self.jpeg_history else None
        if not path: return
        z = self.main_zoom_map.get(path, self.default_main_zoom)
        if zoom_in:
            z = min(z * 1.25, 8.0)
        else:
            z = max(z / 1.25, 0.2)
        self.main_zoom_map[path] = z
        self.main_canvas.refresh_rotation_or_quality(force=True)
        self.default_main_zoom = z

    def _compare_zoom(self, zoom_in=True):
        path = self.compare_path
        if not path: return
        z = self.compare_zoom_map.get(path, 1.0)
        if zoom_in:
            z = min(z * 1.25, 8.0)
        else:
            z = max(z / 1.25, 0.2)
        self.compare_zoom_map[path] = z
        self.compare_canvas.refresh_rotation_or_quality(force=True)

    def _make_rotate_buttons(self, canvas, which="main"):
        frame = ttk.Frame(canvas, style="RotBtn.TFrame")
        def rotate_left():
            if which == "main":
                deg = (self.get_main_rotation() - 90) % 360
                self.set_main_rotation(deg)
            else:
                path = self.compare_path
                if path:
                    deg = (self.compare_rotation_map.get(path, 0) - 90) % 360
                    self.set_compare_rotation(deg)
        def rotate_right():
            if which == "main":
                deg = (self.get_main_rotation() + 90) % 360
                self.set_main_rotation(deg)
            else:
                path = self.compare_path
                if path:
                    deg = (self.compare_rotation_map.get(path, 0) + 90) % 360
                    self.set_compare_rotation(deg)
        def reset():
            if which == "main":
                self.set_main_rotation(0)
            else:
                path = self.compare_path
                if path:
                    self.set_compare_rotation(0)
        ttk.Button(frame, text="⟲ 90°", width=7, command=rotate_left).pack(side="left", padx=2)
        ttk.Button(frame, text="원래대로", width=7, command=reset).pack(side="left", padx=2)
        ttk.Button(frame, text="⟳ 90°", width=7, command=rotate_right).pack(side="left", padx=2)
        ttk.Label(frame, text="마우스휠로 확대/축소").pack(side="left", padx=8)
        return frame

    def refresh_thumbnails(self):
        save_dir = self.save_dir_var.get()
        base_filename = self.base_filename_var.get()
        files = []
        for ext in ("jpg", "jpeg", "png", "JPG", "JPEG", "PNG"):
            pattern = os.path.join(save_dir, f"{base_filename}*.{ext}")
            files.extend(glob.glob(pattern))
        files = sorted(files, key=os.path.getmtime, reverse=True)
        self.thumb_gallery.clear()
        self.jpeg_history = []
        for f in files:
            self.thumb_gallery.add_thumbnail(f)
            self.jpeg_history.append(f)
        if self.jpeg_history:
            self.main_canvas.set_image(self.jpeg_history[0])

    def show_jpeg_preview(self, image_path):
        self.refresh_thumbnails()
        # 중복 방지(새 파일만 추가)
        if image_path not in self.jpeg_history:
            self.jpeg_history.insert(0, image_path)
            self.thumb_gallery.add_thumbnail(image_path)
        if len(self.jpeg_history) > 1 and self.compare_path is None:
            self.compare_path = self.jpeg_history[1]
            self.compare_canvas.set_image(self.compare_path)
        path = image_path
        if path not in self.main_rotation_map:
            self.main_rotation_map[path] = self.default_main_rotation
        if path not in self.main_zoom_map:
            self.main_zoom_map[path] = self.default_main_zoom
        self.main_canvas.set_image(image_path)
        self.main_canvas.refresh_rotation_or_quality(force=True)
        if self.pose_estimation_enabled.get() and not self.pose_estimation_in_progress:
            import threading
            self.pose_estimation_thread = threading.Thread(
                target=self._estimate_pose,
                args=(image_path,),
                daemon=True
            )
            self.pose_estimation_thread.start()

    def set_compare_image(self, image_path):
        self.compare_path = image_path
        self.compare_canvas.set_image(image_path)
        if image_path not in self.compare_rotation_map:
            self.compare_rotation_map[image_path] = 0
        if image_path not in self.compare_zoom_map:
            self.compare_zoom_map[image_path] = 1.0
        self.compare_canvas.refresh_rotation_or_quality(force=True)

    def on_thumbnail_click(self, image_path):
        self.set_compare_image(image_path)

    def connect_camera(self):
        self.camera_status.config(text="카메라 검색 중...")
        self.root.update()
        camera_list = []
        for _ in range(3):
            camera_list = list_cameras()
            if camera_list: break
            time.sleep(1)
        if not camera_list:
            self.camera_status.config(text="카메라가 연색결되어 있지 않습니다.")
            self.camera = None
            return
        try:
            self.event_stop.set()
            if self.event_thread and self.event_thread.is_alive():
                self.event_thread.join(timeout=2)
            if self.camera:
                with self.camera_lock:
                    self.camera.exit()
            self.camera = gp.Camera()
            with self.camera_lock:
                self.camera.init()
            self.camera_status.config(text=f"연결됨: {camera_list[0][0]}")
            self.load_settings()
            self.event_stop.clear()
            self.event_thread = threading.Thread(
                target=event_listener,
                args=(
                    self.camera,
                    lambda: self.save_dir_var.get(),
                    lambda: self.base_filename_var.get(),
                    lambda: self.save_format_var.get(),
                    self.notify_saved_from_thread,
                    self.log_from_thread,
                    self.camera_lock,
                    self.event_stop,
                ),
                daemon=True
            )
            self.event_thread.start()
            self.log("카메라 연결 및 이벤트 감시 시작.")
        except Exception as e:
            self.camera_status.config(text=f"카메라 연결 실패: {e}")
            self.log(f"카메라 연결 실패: {e}")
            self.camera = None

    def notify_saved_from_thread(self, path):
        self.log_from_thread(f"자동 저장: {path}")
        ext = os.path.splitext(path)[1].lower()
        # S3 업로드
        if ext in (".jpg", ".jpeg") and self.s3_manager.settings.get('upload_enabled', True):
            self.s3_manager.manual_upload(path)
        if ext in (".jpg", ".jpeg"):
            self.root.after(0, self.show_jpeg_preview, path)

    def log(self, msg):
        timestamp = time.strftime("[%H:%M:%S] ")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"{timestamp}{msg}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def log_from_thread(self, msg):
        self.root.after(0, self.log, msg)

    def load_settings(self):
        if not self.camera:
            self.iso_var.set("N/A")
            self.ss_var.set("N/A")
            self.ap_var.set("N/A")
            self.wb_var.set("N/A")
            self.kelvin_var.set("N/A")
            return
        with self.camera_lock:
            iso = get_camera_setting(self.camera, "iso") or "N/A"
            ss = get_camera_setting(self.camera, "shutterspeed") or "N/A"
            ap = get_camera_setting(self.camera, "aperture")
            if ap is None:
                ap = get_camera_setting(self.camera, "f-number")
            ap = ap or "N/A"
            wb = get_camera_setting(self.camera, "whitebalance")
            if wb is None:
                wb = get_camera_setting(self.camera, "white balance")
            wb = wb or "N/A"
            kelvin = "N/A"
            kelvin_keys = ["colortemperature", "color temperature", "kelvin", "whitebalancekelvin", "whitebalance_kelvin"]
            for key in kelvin_keys:
                v = get_camera_setting(self.camera, key)
                if v is not None:
                    kelvin = str(v)
                    break
        self.iso_var.set(iso)
        self.ss_var.set(ss)
        self.ap_var.set(ap)
        self.wb_var.set(wb)
        self.kelvin_var.set(kelvin)

    def poll_camera_settings(self):
        self.load_settings()
        self.root.after(1000, self.poll_camera_settings)

    def set_iso(self):
        if not self.camera: return
        iso = simpledialog.askstring("ISO 설정", f"ISO 값을 직접 입력하세요 (현재: {self.iso_var.get()})", parent=self.root)
        if not iso: return
        with self.camera_lock:
            ok, msg = set_camera_config_with_choices(self.camera, "iso", iso)
        messagebox.showinfo("ISO 설정", msg)
        self.load_settings()

    def set_ss(self):
        if not self.camera: return
        ss = simpledialog.askstring("셔터속도 설정", f"셔터속도 값을 직접 입력하세요 (현재: {self.ss_var.get()})", parent=self.root)
        if not ss: return
        with self.camera_lock:
            ok, msg = set_camera_config_with_choices(self.camera, "shutterspeed", ss)
        messagebox.showinfo("셔터속도 설정", msg)
        self.load_settings()

    def set_ap(self):
        if not self.camera: return
        ap = simpledialog.askstring("조리개 설정", f"조리개 값을 직접 입력하세요 (현재: {self.ap_var.get()})", parent=self.root)
        if not ap: return
        with self.camera_lock:
            ok, msg = set_aperture(self.camera, ap)
        messagebox.showinfo("조리개 설정", msg)
        self.load_settings()

    def select_dir(self):
        d = filedialog.askdirectory(initialdir=self.save_dir_var.get())
        if d:
            self.save_dir_var.set(d)

    def capture(self):
        """촬영 함수"""
        if not self.camera:
            messagebox.showerror("오류", "카메라가 연결되어 있지 않습니다!")
            return

        save_dir = self.save_dir_var.get()
        base_filename = self.base_filename_var.get()
        save_format = self.save_format_var.get()

        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        try:
            self.log("PC에서 촬영 명령 실행")
            with self.camera_lock:
                file_path = self.camera.capture(gp.GP_CAPTURE_IMAGE)
                folder = file_path.folder
                name = file_path.name
                base_name, ext = os.path.splitext(name)
                files = self.camera.folder_list_files(folder)[0]

                raw_exts = [".arw", ".raw", ".nef", ".cr2", ".cr3", ".orf", ".rw2", ".dng"]
                jpeg_exts = [".jpg", ".jpeg"]

                if save_format == "raw":
                    exts = raw_exts
                elif save_format == "jpeg":
                    exts = jpeg_exts
                else:
                    exts = raw_exts + jpeg_exts

                saved = []
                jpeg_saved = None

                for file in files:
                    if file is None or not file.startswith(base_name):
                        continue

                    fext = os.path.splitext(file)[1].lower()
                    if fext in exts:
                        outname = get_unique_filename(save_dir, base_filename, fext)
                        camera_file = gp.CameraFile()
                        self.camera.file_get(folder, file, gp.GP_FILE_TYPE_NORMAL, camera_file)
                        target = os.path.join(save_dir, outname)
                        camera_file.save(target)
                        saved.append(target)
                        self.log(f"PC촬영 저장: {target}")

                        # # JPEG 파일인 경우 S3 업로드 큐에 추가
                        # if fext in jpeg_exts and self.s3_upload_var.get():
                        #     self.s3_manager.queue_upload(target)
                        #     jpeg_saved = target

                if jpeg_saved:
                    self.show_jpeg_preview(jpeg_saved)

                if not saved:
                    messagebox.showerror("촬영 실패", "저장된 파일이 없습니다. (카메라의 저장 포맷, 확장자, 동시 저장 설정을 확인하세요.)")
                else:
                    messagebox.showinfo("촬영 결과", f"저장 완료:\n" + "\n".join(saved))

            time.sleep(1.0)

        except gp.GPhoto2Error as e:
            self.log(f"PC촬영 오류: {e}")
            if e.code in (-53, -110):
                try:
                    with self.camera_lock:
                        self.camera.exit()
                    time.sleep(1)
                    with self.camera_lock:
                        self.camera.init()
                    time.sleep(1)
                except Exception as e2:
                    self.camera_status.config(text=f"카메라 재초기화 실패: {e2}")
                    self.log(f"카메라 재초기화 실패: {e2}")
            messagebox.showerror("촬영 실패", str(e))
        except Exception as e:
            messagebox.showerror("촬영 실패", str(e))
            self.log(f"PC촬영 오류: {e}")
        self.load_settings()

    def on_close(self):
        """프로그램 종료 시 호출"""
        self.event_stop.set()
        if self.event_thread and self.event_thread.is_alive():
            self.event_thread.join(timeout=2)
        # S3 업로드 워커 정지
        if self.s3_manager:
            self.s3_manager.stop_upload_worker()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Sony Camera Tether GUI")
    root.geometry("1680x950")
    root.minsize(1200,600)
    app = CameraGUI(root)
    app.compare_layout_var.trace_add("write", lambda *args: app.update_compare_layout())
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()