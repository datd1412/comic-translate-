from __future__ import annotations

import json
from pathlib import Path
import sys
import pytest

from PIL import Image

PHASE0_DIR = Path(__file__).resolve().parent.parent / "phase0"
if str(PHASE0_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE0_DIR))

from ocr_probe import (  # noqa: E402
    ORIENTATION_RATIO_NOTE,
    compute_timing_summary,
    normalize_paddle_result,
    probe_directory,
)
from eval_ocr import (  # noqa: E402
    GROUND_TRUTH_DISCLAIMER,
    compute_cer,
    evaluate_dataset,
    evaluate_single_image,
    summarize_probe_only,
)
from visualize_probe import visualize_probe_report  # noqa: E402
from stitch_probe import (  # noqa: E402
    NEAR_SEAM_NOTE,
    ensure_outside_project,
    probe_slice_sets,
)


def test_normalize_paddle_v2_and_v3_formats() -> None:
    # Giả lập định dạng PaddleOCR 2.x
    raw_v2 = [
        [
            [[[10, 20], [110, 20], [110, 60], [10, 60]], ("你好世界", 0.9821)],
            [[[200, 300], [350, 300], [350, 340], [200, 340]], ("Hello world", 0.9154)],
        ]
    ]
    lines_v2 = normalize_paddle_result(raw_v2)
    assert len(lines_v2) == 2
    assert lines_v2[0]["id"] == 1
    assert lines_v2[0]["bbox"] == [10, 20, 110, 60]
    assert lines_v2[0]["text"] == "你好世界"
    assert lines_v2[0]["score"] == 0.9821

    # Giả lập định dạng PaddleOCR 3.x (PP-OCRv4/v5 predict output)
    raw_v3 = [
        {
            "rec_texts": ["第一行", "第二行"],
            "rec_scores": [0.99, 0.87],
            "dt_polys": [
                [[15, 25], [120, 25], [120, 70], [15, 70]],
                [[15, 80], [120, 80], [120, 120], [15, 120]],
            ],
        }
    ]
    lines_v3 = normalize_paddle_result(raw_v3)
    assert len(lines_v3) == 2
    assert lines_v3[1]["id"] == 2
    assert lines_v3[1]["bbox"] == [15, 80, 120, 120]
    assert lines_v3[1]["text"] == "第二行"
    assert lines_v3[1]["score"] == 0.87


def test_timing_summary_excludes_first_image_warmup() -> None:
    timings = [2500.0, 400.0, 500.0, 600.0, 500.0]
    summary = compute_timing_summary(timings)
    assert summary["total_images"] == 5
    assert summary["first_image_warmup_ms"] == 2500.0
    assert summary["mean_ms_excluding_first"] == 500.0
    assert summary["median_ms_excluding_first"] == 500.0
    assert summary["all_images_mean_ms"] == 900.0


def test_cer_and_block_evaluation_with_missed_and_extra_sfx() -> None:
    assert compute_cer("你好世界", "你好世界") == 0.0
    assert compute_cer("你好世界", "你好世X") == 0.25

    gt_blocks = [
        {"id": "b1", "bbox": [100, 100, 300, 250], "text": "你好世界"},
        {"id": "b2", "bbox": [400, 400, 600, 550], "text": "再见朋友"},
    ]
    pred_lines = [
        {"id": 1, "bbox": [110, 110, 290, 160], "text": "你好", "score": 0.96},
        {"id": 2, "bbox": [110, 170, 290, 230], "text": "世界", "score": 0.95},
        {"id": 3, "bbox": [50, 600, 140, 650], "text": "轰隆!!", "score": 0.61},
        {"id": 4, "bbox": [700, 1150, 890, 1190], "text": "baozimh.org", "score": 0.99},
    ]

    result = evaluate_single_image(gt_blocks, pred_lines)
    assert result["gt_block_count"] == 2
    assert result["missed_blocks"] == 1
    assert result["extra_blocks"] == 2
    assert result["cer"] == 0.5


def test_probe_geometry_measurements_tall_image_orientation_and_edge_distance(tmp_path: Path) -> None:
    img_dir = tmp_path / "pages"
    img_dir.mkdir()
    # page_01: 800 x 1200 (không cao hơn 1500 px -> "ảnh thường")
    Image.new("RGB", (800, 1200), color=(255, 255, 255)).save(img_dir / "page_01.png")
    # page_02: 800 x 2400 (cao hơn 1500 px -> "ảnh cao")
    Image.new("RGB", (800, 2400), color=(255, 255, 255)).save(img_dir / "page_02.png")
    # page_03: 800 x 1600 (cao hơn 1500 px -> "ảnh cao")
    Image.new("RGB", (800, 1600), color=(255, 255, 255)).save(img_dir / "page_03.png")

    def fake_runner(image_path: str):
        name = Path(image_path).name
        if name == "page_01.png":
            # Khối ngang: rộng 200 (100..300), cao 50 (100..150) -> tỉ lệ 50/200 = 0.25 -> "ngang"
            # Khoảng cách tới mép: left=100, top=100, right=500, bottom=1050 -> min=100 px
            return [[[[[100, 100], [300, 100], [300, 150], [100, 150]], ("Hello there", 0.98)]]]
        if name == "page_02.png":
            return [
                # Khối dọc: rộng 40 (740..780), cao 160 (200..360) -> tỉ lệ 160/40 = 4.0 -> "dọc"
                # Khoảng cách tới mép phải = 800 - 780 = 20 px
                [[[740, 200], [780, 200], [780, 360], [740, 360]], ("竖排文字", 0.95)],
                # Khối sát đáy: y2=2392 trên ảnh cao 2400 -> cách mép dưới 8 px
                [[[600, 2350], [750, 2350], [750, 2392], [600, 2392]], ("!", 0.72)],
            ]
        return [[]]

    probe_report = probe_directory(img_dir, lang="zh", runner=fake_runner, dump_raw_schema=True)
    assert probe_report["orientation_ratio_note"] == ORIENTATION_RATIO_NOTE

    img1, img2, img3 = probe_report["images"]
    assert img1["is_tall_image"] is False
    assert img1["height_label"] == "ảnh thường"
    line1 = img1["lines"][0]
    assert line1["aspect_ratio_h_over_w"] == 0.25
    assert line1["orientation_label"] == "ngang"
    assert line1["nearest_edge_distance_px"] == 100

    assert img2["is_tall_image"] is True
    assert img2["height_label"] == "ảnh cao"
    line2_vert = img2["lines"][0]
    assert line2_vert["aspect_ratio_h_over_w"] == 4.0
    assert line2_vert["orientation_label"] == "dọc"
    assert line2_vert["nearest_edge_distance_px"] == 20
    line2_bottom = img2["lines"][1]
    assert line2_bottom["nearest_edge_distance_px"] == 8

    assert img3["is_tall_image"] is True
    assert img3["height_label"] == "ảnh cao"

    # Kiểm tra tương thích với evaluate_dataset và summarize_probe_only
    gt_data = {
        "images": {
            "page_01.png": [{"id": "b1", "bbox": [90, 90, 310, 210], "text": "Hello there"}],
            "page_02.png": [{"id": "b1", "bbox": [730, 190, 790, 370], "text": "竖排文字"}],
            "page_03.png": [{"id": "b1", "bbox": [90, 90, 310, 210], "text": "Missed line"}],
        }
    }
    eval_report = evaluate_dataset(gt_data, probe_report)
    assert eval_report["mode"] == "with_ground_truth"
    assert GROUND_TRUTH_DISCLAIMER in eval_report["ground_truth_notice"]
    assert eval_report["summary"]["total_missed_blocks"] == 1
    assert eval_report["summary"]["total_extra_blocks_sfx_or_noise"] == 1

    probe_only_stats = summarize_probe_only(probe_report)
    assert probe_only_stats["mode"] == "probe_only_no_ground_truth"
    assert probe_only_stats["summary"]["total_images"] == 3


def test_visualize_probe_writes_to_external_directory(tmp_path: Path) -> None:
    images_dir = tmp_path / "raw_pages"
    images_dir.mkdir()
    img_path = images_dir / "page_01.png"
    base_img = Image.new("RGB", (600, 800), color=(255, 255, 255))
    base_img.save(img_path)

    probe_json_path = tmp_path / "probe_out.json"
    probe_payload = {
        "lang": "zh",
        "images": [
            {
                "image_name": "page_01.png",
                "width": 600,
                "height": 800,
                "elapsed_ms": 420.5,
                "line_count": 2,
                "lines": [
                    {
                        "id": 1,
                        "bbox": [50, 60, 250, 120],
                        "polygon": [[50, 60], [250, 60], [250, 120], [50, 120]],
                        "text": "你好",
                        "score": 0.96,
                    },
                    {
                        "id": 2,
                        "bbox": [300, 400, 480, 470],
                        "polygon": [[300, 400], [480, 400], [480, 470], [300, 470]],
                        "text": "轰!",
                        "score": 0.65,
                    },
                ],
            }
        ],
    }
    probe_json_path.write_text(json.dumps(probe_payload), encoding="utf-8")

    external_vis_dir = tmp_path / "external_output_vis"
    saved_files = visualize_probe_report(
        images_dir=images_dir,
        probe_json_path=probe_json_path,
        output_dir=external_vis_dir,
    )
    assert len(saved_files) == 1
    assert saved_files[0].exists()
    assert saved_files[0].parent == external_vis_dir.resolve()
    with Image.open(saved_files[0]) as vis_img:
        assert vis_img.size == (600, 800)
        assert vis_img.getpixel((50, 60)) != (255, 255, 255)


def test_stitch_probe_measures_seams_and_blocks_without_merging(tmp_path: Path) -> None:
    set_dir = tmp_path / "set_baozimh_01"
    set_dir.mkdir()
    # 3 lát liên tiếp, mỗi lát 600 x 500 px -> có 2 đường nối (seam 1 và seam 2)
    Image.new("RGB", (600, 500), color=(255, 255, 255)).save(set_dir / "slice_01.png")
    Image.new("RGB", (600, 500), color=(255, 255, 255)).save(set_dir / "slice_02.png")
    Image.new("RGB", (600, 500), color=(255, 255, 255)).save(set_dir / "slice_03.png")

    def fake_stitch_runner(image: Image.Image, label: str):
        # Đường nối 1 (slice_01 + slice_02): cả 2 bên đều có khối nằm trong 40 px quanh đường nối
        if label == "slice_01.png":
            # y2 = 485 trên lát cao 500 -> cách đường nối 15 px (<= 40 px), cao 35 px, ký tự cuối '半'
            return [[[[[100, 450], [300, 450], [300, 485], [100, 485]], ("被切断上半", 0.91)]]]
        if label == "slice_02.png":
            return [
                # y1 = 12 trên lát dưới -> cách đường nối 12 px (<= 40 px), cao 30 px, ký tự cuối '句'
                [[[100, 12], [300, 12], [300, 42], [100, 42]], ("被切断下半句", 0.89)],
                # Khối ở xa mép dưới: y2 = 300 -> cách đường nối 2 là 500 - 300 = 200 px (> 40 px)
                [[[120, 260], [320, 260], [320, 300], [120, 300]], ("中间正常对话!", 0.97)],
            ]
        if label == "slice_03.png":
            # y1 = 25 -> cách đường nối 2 là 25 px (<= 40 px), nên đường nối 2 chỉ có 1 bên nằm trong 40 px
            return [[[[[150, 25], [350, 25], [350, 65], [150, 65]], ("下片顶部文字?", 0.93)]]]
        if label == "slice_01__slice_02_stitched":
            # Khi ghép lại thành dải 600 x 1000, giả lập OCR đọc thành 1 khối nguyên vẹn xuyên qua seam y=500
            return [[[[[100, 450], [300, 450], [300, 542], [100, 542]], ("被切断上半被切断下半句", 0.96)]]]
        if label == "slice_02__slice_03_stitched":
            return [
                [[[100, 12], [300, 12], [300, 42], [100, 42]], ("被切断下半句", 0.89)],
                [[[120, 260], [320, 260], [320, 300], [120, 300]], ("中间正常对话!", 0.97)],
                [[[150, 525], [350, 525], [350, 565], [150, 565]], ("下片顶部文字?", 0.93)],
            ]
        return [[]]

    vis_dir = tmp_path / "vis_stitched_out"
    report = probe_slice_sets(
        slice_dirs=[set_dir],
        lang="zh",
        vis_output_dir=vis_dir,
        runner=fake_stitch_runner,
        allow_vis_in_tests=True,
    )

    assert report["near_seam_note"] == NEAR_SEAM_NOTE
    assert report["summary"]["total_slice_sets"] == 1
    assert report["summary"]["total_seams"] == 2
    assert report["summary"]["seams_with_near_block_at_least_one_side"] == 2
    assert report["summary"]["seams_with_near_block_both_sides"] == 1

    seam1, seam2 = report["sets"][0]["seams"]
    assert seam1["closest_block_top_side"]["distance_to_seam_px"] == 15
    assert seam1["closest_block_top_side"]["line_height_px"] == 35
    assert seam1["closest_block_top_side"]["last_char"] == "半"
    assert seam1["closest_block_bottom_side"]["distance_to_seam_px"] == 12
    assert seam1["closest_block_bottom_side"]["line_height_px"] == 30
    assert seam1["closest_block_bottom_side"]["last_char"] == "句"
    assert seam1["has_block_within_40px_both_sides"] is True
    assert seam1["block_count_comparison"]["sum_before_stitch"] == 3
    assert seam1["block_count_comparison"]["stitched_strip_blocks"] == 1

    assert seam2["has_block_within_40px_top"] is False
    assert seam2["has_block_within_40px_bottom"] is True
    assert seam2["has_block_within_40px_at_least_one_side"] is True
    assert seam2["has_block_within_40px_both_sides"] is False

    # Kiểm tra ảnh dải ghép đã vẽ khung và kẻ đường nối màu hồng tím (217, 70, 239) tại y = 500
    vis_path_1 = Path(seam1["visualized_strip_path"])
    assert vis_path_1.exists()
    with Image.open(vis_path_1) as st_img:
        assert st_img.size == (600, 1000)
        assert st_img.getpixel((590, 500)) == (217, 70, 239)

    # Kiểm tra chặn ghi ảnh vào bên trong thư mục dự án
    with pytest.raises(ValueError, match="không được nằm trong thư mục dự án"):
        ensure_outside_project(PHASE0_DIR / "forbidden_vis_inside_project", allow_in_tests=False)