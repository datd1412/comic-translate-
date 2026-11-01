from __future__ import annotations

import json
from pathlib import Path
import sys

from PIL import Image

PHASE1A_DIR = Path(__file__).resolve().parent.parent / "phase1a"
if str(PHASE1A_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE1A_DIR))

from bench_speed import (  # noqa: E402
    _wrap_predictor_timing,
    build_benchmark_configs,
    run_speed_benchmark,
)
from rec_compare import (  # noqa: E402
    compare_low_score_lines,
    format_comparison_table,
)


def test_wrap_predictor_timing_captures_generator_inference_time() -> None:
    class FakeGeneratorPredictor:
        def predict(self, img_path: str):
            # Giả lập PaddleX 3.x trả về generator
            yield {"rec_texts": ["A"], "rec_scores": [0.9], "dt_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]]}

    bucket: list[float] = []
    pred = FakeGeneratorPredictor()
    assert _wrap_predictor_timing(pred, bucket) is True

    items = list(pred.predict("dummy.png"))
    assert len(items) == 1
    assert len(bucket) >= 1
    assert sum(bucket) >= 0.0


def test_bench_speed_runs_at_least_3_configs_and_reports_separate_det_and_rec(tmp_path: Path) -> None:
    zh_dir = tmp_path / "baozimh_sample"
    en_dir = tmp_path / "hivetoons_sample"
    zh_dir.mkdir()
    en_dir.mkdir()

    for i in range(1, 3):
        Image.new("RGB", (1000, 1436), color=(255, 255, 255)).save(zh_dir / f"zh_{i}.png")
        Image.new("RGB", (800, 5000), color=(255, 255, 255)).save(en_dir / f"en_{i}.png")

    configs = build_benchmark_configs(cpu_threads=4)
    assert len(configs) >= 3

    def fake_runner_factory(lang: str, cfg: dict):
        is_mobile = cfg.get("use_mobile", False)
        det_val = 120.0 if is_mobile else 450.0
        rec_val = 210.0 if is_mobile else 880.0

        def _runner(image_path: str):
            return {
                "raw_out": [
                    {
                        "rec_texts": ["テスト"],
                        "rec_scores": [0.95],
                        "dt_polys": [[[10, 10], [80, 10], [80, 50], [10, 50]]],
                    }
                ],
                "total_ms": det_val + rec_val,
                "det_ms": det_val,
                "rec_ms": rec_val,
                "cls_ms": 0.0 if not cfg.get("use_textline_orientation", True) else 15.0,
            }

        meta = {
            "paddle_lang": lang,
            "loaded_model_note": "mobile_mock" if is_mobile else "server_mock",
            "effective_kwargs": {},
            "model_init_ms": 50.0,
            "hook_status": {"det_hooked": True, "rec_hooked": True, "cls_hooked": True},
        }
        return _runner, meta

    report = run_speed_benchmark(
        datasets=[(zh_dir, "zh"), (en_dir, "en")],
        configs=configs,
        cpu_threads=4,
        runner_factory=fake_runner_factory,
    )

    assert "cpu_model" in report["environment"]
    assert report["environment"]["configured_cpu_threads"] == 4
    assert "paddlepaddle_version" in report["environment"]
    assert len(report["configs"]) == 4

    cfg_a = report["configs"][0]["datasets"][0]["summary"]
    cfg_b = report["configs"][1]["datasets"][0]["summary"]
    assert cfg_a["mean_det_ms_excluding_first"] == 450.0
    assert cfg_a["mean_rec_ms_excluding_first"] == 880.0
    assert cfg_b["mean_det_ms_excluding_first"] == 120.0
    assert cfg_b["mean_rec_ms_excluding_first"] == 210.0


def test_rec_compare_filters_below_0_6_and_handles_missing_chinese_cht_and_2x_crop(tmp_path: Path) -> None:
    img_dir = tmp_path / "pages"
    img_dir.mkdir()
    Image.new("RGB", (600, 800), color=(255, 255, 255)).save(img_dir / "page_01.png")

    probe_json = tmp_path / "baozimh_probe.json"
    probe_payload = {
        "lang": "zh",
        "input_dir": str(img_dir),
        "images": [
            {
                "image_name": "page_01.png",
                "width": 600,
                "height": 800,
                "lines": [
                    {
                        "id": 1,
                        "bbox": [100, 100, 160, 140],  # 60 x 40 px (+2px pad mỗi bên -> 64 x 44 px)
                        "text": "好",
                        "score": 0.92,  # >= 0.6 -> phải bỏ qua
                    },
                    {
                        "id": 2,
                        "bbox": [200, 200, 250, 230],  # 50 x 30 px (+2px pad mỗi bên -> 54 x 34 px)
                        "text": "错字",
                        "score": 0.42,  # < 0.6 -> phải nhận dạng lại
                    },
                ],
            }
        ],
    }
    probe_json.write_text(json.dumps(probe_payload), encoding="utf-8")

    observed_sizes: list[tuple[int, int]] = []

    def fake_recognizers_factory(lang: str):
        def _no_orient(crop: Image.Image) -> tuple[str, float]:
            observed_sizes.append(crop.size)
            return ("正字_no_orient", 0.88)

        def _upscale_2x(crop: Image.Image) -> tuple[str, float]:
            observed_sizes.append(crop.size)
            return ("正字_2x", 0.94)

        return {
            "no_orient": _no_orient,
            "chinese_cht": None,  # Giả lập lang chinese_cht không khả dụng
            "upscale_2x": _upscale_2x,
            "chinese_cht_status": "Bỏ qua lang='chinese_cht' vì không khả dụng trong bản cài đặt thử nghiệm.",
        }

    report = compare_low_score_lines(
        probe_json_paths=[probe_json],
        score_threshold=0.6,
        recognizers_factory=fake_recognizers_factory,
    )

    assert report["total_low_score_lines"] == 1
    assert len(report["chinese_cht_notices"]) == 1

    item = report["items"][0]
    assert item["line_id"] == 2
    assert item["old_score"] == 0.42
    assert item["variant_1_no_orient"]["text"] == "正字_no_orient"
    assert item["variant_2_chinese_cht"]["skipped"] is True
    assert item["variant_3_upscale_2x"]["text"] == "正字_2x"

    # Kiểm tra kích thước ảnh crop 2x gấp đôi ảnh crop 1x
    w1, h1 = item["crop_size_1x"]
    w2, h2 = item["crop_size_2x"]
    assert (w2, h2) == (w1 * 2, h1 * 2)
    assert observed_sizes == [(w1, h1), (w2, h2)]

    table_str = format_comparison_table(report)
    assert "page_01.png" in table_str
    assert "正字_no_orient" in table_str
    assert "SKIPPED" in table_str
    assert "正字_2x" in table_str
