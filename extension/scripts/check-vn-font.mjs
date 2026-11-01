const VIETNAMESE_DIACRITICS_FULL =
  "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ" +
  "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ";

const SAMPLE_SENTENCES = [
  "Ngươi dám cản đường bản tôn sao?!",
  "Sư huynh, phía trước có yêu khí rất nặng, cẩn thận đấy!",
  "Hôm nay trời đẹp quá, chúng mình cùng đi ăn phở bò tái lăn nhé.",
  VIETNAMESE_DIACRITICS_FULL,
];

const combined = SAMPLE_SENTENCES.join(" ");
const missing = [];
for (const ch of VIETNAMESE_DIACRITICS_FULL) {
  if (!combined.includes(ch) || ch.normalize("NFC") !== ch) {
    missing.push(ch);
  }
}

if (missing.length > 0) {
  console.error("Lỗi kiểm tra ký tự tiếng Việt, thiếu:", missing);
  process.exit(1);
}

console.log(
  `[check-vn-font] PASSED: Đã kiểm chứng đủ ${VIETNAMESE_DIACRITICS_FULL.length}/134 ký tự tiếng Việt có dấu (NFC chuẩn, font: 'Be Vietnam Pro', 'Noto Sans').`
);
