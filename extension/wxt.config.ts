import { defineConfig } from "wxt";

export default defineConfig({
  manifest: {
    name: "Comic Translate VN",
    version: "1.0.0",
    description:
      "Dịch truyện tranh trực tiếp trên baozimh.org (Trung -> Việt) và hivetoons.org (Anh -> Việt)",
    permissions: [
      "storage",
      "identity",
      "activeTab",
      "scripting",
      "declarativeNetRequest",
      "declarativeNetRequestWithHostAccess",
      "cookies",
    ],
    host_permissions: ["<all_urls>"],
    action: {
      default_title: "Comic Translate VN",
    },
  },
});
