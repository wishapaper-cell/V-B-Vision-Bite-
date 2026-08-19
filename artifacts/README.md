# Artifacts

该目录存放发布物和调试产物，不是源代码。

```text
releases/android/          APK/AAB
debug/logs/                本地调试日志
debug/device-screenshots/  设备截图
legacy-shortcuts/          迁移前的本地快捷方式
```

二进制发布物、日志和截图默认通过 `.gitignore` 排除。正式发布应由 CI/CD 或制品库管理，并记录版本、提交号、构建环境和校验和。
