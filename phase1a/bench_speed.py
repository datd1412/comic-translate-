from __future__ import annotations

import argparse
import inspect
import json
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any, Callable

from PIL import Image

PHASE0_DIR = Path(__file__).resolve().parent.parent / "phase0"
import sys

if str(PHASE0_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE0_DIR))

from ocr_probe import IMAGE_EXTENSIONS, LANG_MAP, normalize_paddle_result  # noqa: E402


def get_cpu_model_name() -> str:
    """Lấy tên CPU thực tế trên Windows / Linux mà không cần cài thêm thư viện ngoài."""
    if platform.system() == "Windows":
        try:
            import winreg  # type: ignore

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            cpu_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            if cpu_name:
                return str(cpu_name).strip()
        except Exception:
            pass
    proc = platform.processor()
    if proc:
        return proc
    return "unknown_cpu"


def collect_runtime_env_info(cpu_threads: int | None = None) -> dict[str, Any]:
    """Thu thập thông tin CPU, số luồng và phiên bản paddle / paddleocr / paddlex."""
    paddle_ver = "not_installed"
    paddleocr_ver = "not_installed"
    paddlex_ver = "not_installed"

    try:
        import paddle  # type: ignore

        paddle_ver = getattr(paddle, "__version__", "unknown")
    except Exception:
        pass

    try:
        import paddleocr  # type: ignore

        paddleocr_ver = getattr(paddleocr, "__version__", "unknown")
    except Exception:
        pass

    try:
        import paddlex  # type: ignore

        paddlex_ver = getattr(paddlex, "__version__", "unknown")
    except Exception:
        pass

    return {
        "os": f"{platform.system()} {platform.release()}",
        "python_version": platform.python_version(),
        "cpu_model": get_cpu_model_name(),
        "logical_cpu_cores": os.cpu_count(),
        "configured_cpu_threads": cpu_threads,
        "omp_num_threads_env": os.environ.get("OMP_NUM_THREADS"),
        "mkl_num_threads_env": os.environ.get("MKL_NUM_THREADS"),
        "paddlepaddle_version": paddle_ver,
        "paddleocr_version": paddleocr_ver,
        "paddlex_version": paddlex_ver,
    }


def build_benchmark_configs(cpu_threads: int | None = None) -> list[dict[str, Any]]:
    """
    Trả về 4 cấu hình kiểm thử tốc độ (tối thiểu 3 cấu hình theo yêu cầu Bước 1A):
    (a) current_default: Cấu hình hiện tại như ở Phase 0 (mặc định PP-OCRv5_server + bật textline_orientation).
    (b) mobile_models: Chuyển sang bộ model mobile (PP-OCRv5_mobile_det + PP-OCRv5_mobile_rec).
    (c1) no_orient_limit_960: Giữ model mặc định nhưng tắt use_textline_orientation và hạ cạnh tối đa det xuống 960 px.
    (c2) mobile_no_orient_limit_960: Kết hợp model mobile + tắt use_textline_orientation + hạ cạnh tối đa det xuống 960 px.
    """
    common_extra: dict[str, Any] = {}
    if cpu_threads is not None:
        common_extra["cpu_threads"] = cpu_threads

    return [
        {
            "config_id": "a_current_default",
            "title": "(a) Cấu hình hiện tại (mặc định server model + bật textline orientation)",
            "use_mobile": False,
            "use_textline_orientation": True,
            "text_det_limit_side_len": None,
            "text_det_limit_type": None,
            "extra_kwargs": dict(common_extra),
        },
        {
            "config_id": "b_mobile_models",
            "title": "(b) Model Mobile (PP-OCRv5_mobile_det + PP-OCRv5_mobile_rec)",
            "use_mobile": True,
            "use_textline_orientation": True,
            "text_det_limit_side_len": None,
            "text_det_limit_type": None,
            "extra_kwargs": dict(common_extra),
        },
        {
            "config_id": "c1_no_orient_limit_960",
            "title": "(c1) Tắt use_textline_orientation + hạ cạnh tối đa det xuống 960 px",
            "use_mobile": False,
            "use_textline_orientation": False,
            "text_det_limit_side_len": 960,
            "text_det_limit_type": "max",
            "extra_kwargs": dict(common_extra),
        },
        {
            "config_id": "c2_mobile_no_orient_limit_960",
            "title": "(c2) Kết hợp Model Mobile + tắt use_textline_orientation + hạ cạnh tối đa 960 px",
            "use_mobile": True,
            "use_textline_orientation": False,
            "text_det_limit_side_len": 960,
            "text_det_limit_type": "max",
            "extra_kwargs": dict(common_extra),
        },
    ]


def _wrap_predictor_timing(target_obj: Any, bucket: list[float]) -> bool:
    """
    Gắn bộ đo thời gian vào đối tượng predictor con (det hoặc rec) trong PaddleOCR / PaddleX.
    Xử lý đúng cả hàm trả về trực tiếp lẫn hàm generator (yield) của PaddleX 3.x.
    """
    if target_obj is None:
        return False

    state = {"active": False}
    hooked = False

    for method_name in ("predict", "__call__", "process"):
        if not hasattr(target_obj, method_name):
            continue
        if method_name == "__call__":
            # Trong Python, gọi obj(...) tra cứu __call__ trên class, nên ta ưu tiên bọc predict / process trên instance
            continue
        orig_fn = getattr(target_obj, method_name)
        if not callable(orig_fn):
            continue

        def _make_wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
            def _wrapped(*args: Any, **kwargs: Any) -> Any:
                if state["active"]:
                    return fn(*args, **kwargs)
                state["active"] = True
                t0 = time.perf_counter()
                try:
                    res = fn(*args, **kwargs)
                    if inspect.isgenerator(res):
                        def _timed_gen():
                            try:
                                it = iter(res)
                                while True:
                                    t_step = time.perf_counter()
                                    try:
                                        item = next(it)
                                    except StopIteration:
                                        bucket.append((time.perf_counter() - t_step) * 1000.0)
                                        break
                                    bucket.append((time.perf_counter() - t_step) * 1000.0)
                                    yield item
                            finally:
                                state["active"] = False

                        return _timed_gen()
                    else:
                        bucket.append((time.perf_counter() - t0) * 1000.0)
                        state["active"] = False
                        return res
                except Exception:
                    state["active"] = False
                    raise

            return _wrapped

        try:
            setattr(target_obj, method_name, _make_wrapper(orig_fn))
            hooked = True
        except Exception:
            pass

    return hooked


def _discover_and_hook_submodels(
    ocr_engine: Any,
    det_bucket: list[float],
    rec_bucket: list[float],
    cls_bucket: list[float],
) -> dict[str, bool]:
    """
    Tìm các model con (Detection, Recognition, Orientation) bên trong PaddleOCR 3.x / PaddleX 3.x
    hoặc PaddleOCR 2.x để đo thời gian riêng cho bước detect và bước recognize.
    """
    hook_status = {"det_hooked": False, "rec_hooked": False, "cls_hooked": False}

    # Duyệt các đối tượng pipeline bên trong ocr_engine (tối đa 3 tầng)
    candidates: list[Any] = [ocr_engine]
    for attr in ("paddlex_pipeline", "_pipeline", "pipeline", "_ocr_pipeline"):
        sub = getattr(ocr_engine, attr, None)
        if sub is not None:
            candidates.append(sub)
            for inner_attr in ("_pipeline", "pipeline"):
                inner = getattr(sub, inner_attr, None)
                if inner is not None:
                    candidates.append(inner)

    for holder in candidates:
        for name in dir(holder):
            if name.startswith("__"):
                continue
            try:
                val = getattr(holder, name)
            except Exception:
                continue
            if val is None:
                continue
            low_name = name.lower()
            cls_name = type(val).__name__.lower()

            if (
                "text_det" in low_name
                or low_name in ("det_model", "text_detector")
                or "detpredictor" in cls_name
                or "textdetector" in cls_name
            ) and not hook_status["det_hooked"]:
                if _wrap_predictor_timing(val, det_bucket):
                    hook_status["det_hooked"] = True

            elif (
                "text_rec" in low_name
                or low_name in ("rec_model", "text_recognizer")
                or "recpredictor" in cls_name
                or "textrecognizer" in cls_name
            ) and not hook_status["rec_hooked"]:
                if _wrap_predictor_timing(val, rec_bucket):
                    hook_status["rec_hooked"] = True

            elif (
                "textline_orientation" in low_name
                or "angle_cls" in low_name
                or "text_cls" in low_name
            ) and not hook_status["cls_hooked"]:
                if _wrap_predictor_timing(val, cls_bucket):
                    hook_status["cls_hooked"] = True

    return hook_status


def create_timed_paddle_runner(
    lang: str,
    config: dict[str, Any],
) -> tuple[Callable[[str], dict[str, Any]], dict[str, Any]]:
    """
    Khởi tạo PaddleOCR theo cấu hình chỉ định và trả về:
      (hàm chạy 1 ảnh trả về {raw_result, total_ms, det_ms, rec_ms, cls_ms}, metadata_khởi_tạo)
    """
    from paddleocr import PaddleOCR  # type: ignore

    paddle_lang = LANG_MAP.get(lang.lower(), lang)
    init_sig = inspect.signature(PaddleOCR.__init__)
    accepts_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in init_sig.parameters.values()
    )

    def _can_pass(param_name: str) -> bool:
        return accepts_var_keyword or (param_name in init_sig.parameters)

    kwargs: dict[str, Any] = {}
    if _can_pass("use_doc_orientation_classify"):
        kwargs["use_doc_orientation_classify"] = False
    if _can_pass("use_doc_unwarping"):
        kwargs["use_doc_unwarping"] = False

    use_orient = bool(config.get("use_textline_orientation", True))
    if _can_pass("use_textline_orientation"):
        kwargs["use_textline_orientation"] = use_orient
    elif _can_pass("use_angle_cls"):
        kwargs["use_angle_cls"] = use_orient

    limit_side = config.get("text_det_limit_side_len")
    limit_type = config.get("text_det_limit_type")
    if limit_side is not None:
        if _can_pass("text_det_limit_side_len"):
            kwargs["text_det_limit_side_len"] = int(limit_side)
        elif _can_pass("det_limit_side_len"):
            kwargs["det_limit_side_len"] = int(limit_side)
    if limit_type is not None:
        if _can_pass("text_det_limit_type"):
            kwargs["text_det_limit_type"] = str(limit_type)
        elif _can_pass("det_limit_type"):
            kwargs["det_limit_type"] = str(limit_type)

    for k, v in config.get("extra_kwargs", {}).items():
        if v is not None and _can_pass(k):
            kwargs[k] = v

    t_init0 = time.perf_counter()
    loaded_model_note = "default_for_lang"

    if config.get("use_mobile"):
        # Thử nạp PP-OCRv5_mobile trước; nếu bản cài đặt hoặc ngôn ngữ cần tên khác thì fallback sang PP-OCRv4_mobile
        mobile_candidates = [
            ("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec"),
            ("PP-OCRv4_mobile_det", "PP-OCRv4_mobile_rec"),
        ]
        ocr_engine = None
        last_err: Exception | None = None
        for det_name, rec_name in mobile_candidates:
            try_kwargs = dict(kwargs)
            if _can_pass("text_detection_model_name"):
                try_kwargs["text_detection_model_name"] = det_name
            if _can_pass("text_recognition_model_name"):
                try_kwargs["text_recognition_model_name"] = rec_name
            if _can_pass("lang") and "text_recognition_model_name" not in try_kwargs:
                try_kwargs["lang"] = paddle_lang
            try:
                ocr_engine = PaddleOCR(**try_kwargs)
                loaded_model_note = f"{det_name} + {rec_name}"
                kwargs = try_kwargs
                break
            except Exception as exc:
                last_err = exc
        if ocr_engine is None:
            raise RuntimeError(f"Không thể khởi tạo cấu hình mobile: {last_err}")
    else:
        kwargs["lang"] = paddle_lang
        ocr_engine = PaddleOCR(**kwargs)

    model_init_ms = round((time.perf_counter() - t_init0) * 1000.0, 2)

    det_bucket: list[float] = []
    rec_bucket: list[float] = []
    cls_bucket: list[float] = []
    hook_status = _discover_and_hook_submodels(ocr_engine, det_bucket, rec_bucket, cls_bucket)

    def _run_one(image_path: str) -> dict[str, Any]:
        det_bucket.clear()
        rec_bucket.clear()
        cls_bucket.clear()

        t0 = time.perf_counter()
        if hasattr(ocr_engine, "predict"):
            raw_out = list(ocr_engine.predict(image_path))
        else:
            raw_out = ocr_engine.ocr(image_path)
        total_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        det_ms = round(sum(det_bucket), 2) if det_bucket else None
        rec_ms = round(sum(rec_bucket), 2) if rec_bucket else None
        cls_ms = round(sum(cls_bucket), 2) if cls_bucket else None

        return {
            "raw_out": raw_out,
            "total_ms": total_ms,
            "det_ms": det_ms,
            "rec_ms": rec_ms,
            "cls_ms": cls_ms,
        }

    meta = {
        "paddle_lang": paddle_lang,
        "loaded_model_note": loaded_model_note,
        "effective_kwargs": {k: str(v) for k, v in kwargs.items()},
        "model_init_ms": model_init_ms,
        "hook_status": hook_status,
    }
    return _run_one, meta


def summarize_stage_timings(
    items: list[dict[str, Any]],
) -> dict[str, float | int | None]:
    """
    Tính trung bình và trung vị cho total_ms, det_ms, rec_ms (bỏ ảnh đầu tiên vì warm-up).
    """
    if not items:
        return {
            "image_count": 0,
            "warmup_total_ms": None,
            "warmup_det_ms": None,
            "warmup_rec_ms": None,
            "mean_total_ms_excluding_first": None,
            "mean_det_ms_excluding_first": None,
            "mean_rec_ms_excluding_first": None,
            "median_total_ms_excluding_first": None,
        }

    first = items[0]
    rest = items[1:] if len(items) > 1 else []

    def _mean_key(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [float(r[key]) for r in rows if r.get(key) is not None]
        return round(float(statistics.mean(vals)), 2) if vals else None

    def _median_key(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [float(r[key]) for r in rows if r.get(key) is not None]
        return round(float(statistics.median(vals)), 2) if vals else None

    return {
        "image_count": len(items),
        "warmup_total_ms": first.get("total_ms"),
        "warmup_det_ms": first.get("det_ms"),
        "warmup_rec_ms": first.get("rec_ms"),
        "mean_total_ms_excluding_first": _mean_key(rest, "total_ms"),
        "mean_det_ms_excluding_first": _mean_key(rest, "det_ms"),
        "mean_rec_ms_excluding_first": _mean_key(rest, "rec_ms"),
        "median_total_ms_excluding_first": _median_key(rest, "total_ms"),
    }


def run_speed_benchmark(
    datasets: list[tuple[Path, str]],
    configs: list[dict[str, Any]] | None = None,
    cpu_threads: int | None = None,
    runner_factory: Callable[[str, dict[str, Any]], tuple[Callable[[str], dict[str, Any]], dict[str, Any]]]
    | None = None,
) -> dict[str, Any]:
    """
    Chạy benchmark tốc độ trên danh sách các bộ ảnh [(input_dir, lang), ...]
    với từng cấu hình trong configs.
    """
    active_configs = configs if configs is not None else build_benchmark_configs(cpu_threads=cpu_threads)
    active_factory = runner_factory if runner_factory is not None else create_timed_paddle_runner

    env_info = collect_runtime_env_info(cpu_threads=cpu_threads)
    config_reports: list[dict[str, Any]] = []

    for cfg in active_configs:
        dataset_results: list[dict[str, Any]] = []
        for input_dir, lang in datasets:
            if not input_dir.exists() or not input_dir.is_dir():
                raise FileNotFoundError(f"Thư mục ảnh mẫu không tồn tại: {input_dir}")

            image_files = sorted(
                [
                    p
                    for p in input_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
                ],
                key=lambda p: p.name,
            )
            if not image_files:
                raise ValueError(f"Không có ảnh nào trong thư mục: {input_dir}")

            runner, init_meta = active_factory(lang, cfg)
            per_image_rows: list[dict[str, Any]] = []

            for idx, img_path in enumerate(image_files):
                with Image.open(img_path) as im:
                    w, h = im.size

                timed = runner(str(img_path))
                lines = normalize_paddle_result(timed["raw_out"], image_width=w, image_height=h)

                per_image_rows.append(
                    {
                        "image_name": img_path.name,
                        "width": w,
                        "height": h,
                        "is_warmup_image": idx == 0,
                        "line_count": len(lines),
                        "total_ms": timed["total_ms"],
                        "det_ms": timed["det_ms"],
                        "rec_ms": timed["rec_ms"],
                        "cls_ms": timed.get("cls_ms"),
                    }
                )

            dataset_results.append(
                {
                    "input_dir": str(input_dir.resolve()),
                    "lang": lang,
                    "init_meta": init_meta,
                    "summary": summarize_stage_timings(per_image_rows),
                    "images": per_image_rows,
                }
            )

        config_reports.append(
            {
                "config_id": cfg["config_id"],
                "title": cfg["title"],
                "datasets": dataset_results,
            }
        )

    return {
        "environment": env_info,
        "configs": config_reports,
    }


def print_benchmark_console_report(report: dict[str, Any]) -> None:
    env = report["environment"]
    print("======================================================================")
    print("[Bench Speed - Bước 1A] THÔNG TIN MÔI TRƯỜNG CHẠY")
    print(f"  - Hệ điều hành : {env['os']} (Python {env['python_version']})")
    print(f"  - CPU          : {env['cpu_model']} ({env['logical_cpu_cores']} luồng logic)")
    print(
        f"  - Số luồng cấu hình: cpu_threads={env['configured_cpu_threads']}, "
        f"OMP_NUM_THREADS={env['omp_num_threads_env']}, MKL_NUM_THREADS={env['mkl_num_threads_env']}"
    )
    print(
        f"  - Phiên bản    : paddlepaddle={env['paddlepaddle_version']}, "
        f"paddleocr={env['paddleocr_version']}, paddlex={env['paddlex_version']}"
    )
    print("======================================================================")

    for cfg in report["configs"]:
        print(f"\n>>> Cấu hình: {cfg['title']} [{cfg['config_id']}]")
        for ds in cfg["datasets"]:
            meta = ds["init_meta"]
            s = ds["summary"]
            print(
                f"  * Tập ảnh: {ds['input_dir']} (lang={ds['lang']}) | "
                f"Model: {meta['loaded_model_note']} | Khởi tạo: {meta['model_init_ms']} ms"
            )
            print("    Chi tiết từng ảnh:")
            for img in ds["images"]:
                warm_tag = " [WARM-UP]" if img["is_warmup_image"] else ""
                print(
                    f"      - {img['image_name']} ({img['width']}x{img['height']} px, {img['line_count']} dòng){warm_tag}: "
                    f"total={img['total_ms']} ms | det={img['det_ms']} ms | rec={img['rec_ms']} ms | cls={img['cls_ms']} ms"
                )
            print(
                f"    => TRUNG BÌNH (đã bỏ ảnh đầu): "
                f"total={s['mean_total_ms_excluding_first']} ms | "
                f"det={s['mean_det_ms_excluding_first']} ms | "
                f"rec={s['mean_rec_ms_excluding_first']} ms "
                f"(median total={s['median_total_ms_excluding_first']} ms)"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bước 1A: Benchmark tốc độ PaddleOCR trên 10 ảnh mẫu với các cấu hình khác nhau, "
            "in thời gian riêng cho detect (det_ms) và recognize (rec_ms)."
        )
    )
    parser.add_argument(
        "--baozimh-dir",
        type=Path,
        default=None,
        help="Đường dẫn tuyệt đối tới thư mục 5 ảnh mẫu baozimh (tiếng Trung, lang=zh)",
    )
    parser.add_argument(
        "--hivetoons-dir",
        type=Path,
        default=None,
        help="Đường dẫn tuyệt đối tới thư mục 5 ảnh mẫu hivetoons (tiếng Anh, lang=en)",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Tùy chọn: Chạy trên 1 thư mục ảnh bất kỳ (dùng kèm --lang)",
    )
    parser.add_argument(
        "--lang",
        default="zh",
        choices=["zh", "ch", "en", "ko", "ja"],
        help="Ngôn ngữ khi dùng --input-dir",
    )
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=4,
        help="Số luồng CPU truyền cho PaddleOCR (mặc định: 4)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Đường dẫn tuyệt đối lưu kết quả benchmark ra JSON (ngoài dự án)",
    )
    args = parser.parse_args()

    datasets: list[tuple[Path, str]] = []
    if args.baozimh_dir is not None:
        datasets.append((args.baozimh_dir, "zh"))
    if args.hivetoons_dir is not None:
        datasets.append((args.hivetoons_dir, "en"))
    if args.input_dir is not None:
        datasets.append((args.input_dir, args.lang))

    if not datasets:
        raise ValueError(
            "Hãy cung cấp --baozimh-dir và --hivetoons-dir (hoặc --input-dir kèm --lang)."
        )

    report = run_speed_benchmark(datasets=datasets, cpu_threads=args.cpu_threads)
    print_benchmark_console_report(report)

    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[Bench Speed] Đã lưu báo cáo JSON tại: {args.output_json}")


if __name__ == "__main__":
    main()
