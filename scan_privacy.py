#!/usr/bin/env python3
"""
隐私扫描脚本 — 检查代码中是否有 IP、密码、主机名等敏感信息
在发布到 GitHub 前运行此脚本确保无隐私泄露
"""
import re
import sys
from pathlib import Path

# 需要扫描的文件
SCAN_FILES = [
    'server_agent.py',
    'local_console.py',
    'config_manager.py',
    'deploy.py',
    'setup_ssh_key.py',
    'install.sh',
    '.env.example',
    'README.md',
    'README_EN.md',
    'CHANGELOG.md',
    'DEPLOYMENT.md',
    'skills/server-console/SKILL.md',
]

# 需要排除的文件（含敏感信息，不应上传到 GitHub）
EXCLUDE_FILES = [
    'astrometry_api_server.py',
    'astrometry_dashboard.html',
    'test_api_e2e.py',
    'test_web_api.py',
    '*.conf',
    '*.env',
    'deploy_command.txt',
    'deploy_chunks.sh',
]

# 敏感信息模式
PATTERNS = {
    'IP地址 (192.168)': r'192\.168\.\d+\.\d+',
    'IP地址 (47.97)': r'47\.97\.\d+\.\d+',
    'IP地址 (10.x)': r'10\.\d+\.\d+\.\d+',
    'IP地址 (172.16-31)': r'172\.(1[6-9]|2[0-9]|3[01])\.\d+\.\d+',
    '硬编码密码': r'(password|passwd|pwd|secret|token)\s*=\s*["\'][^"\']{6,}["\']',
    'AstR0口令': r'AstR0|C0ns0le|astro-admin',
    'admin-token': r'admin-token-\d+',
    'API密钥': r'api[_-]?key\s*=\s*["\'][^"\']{8,}["\']',
}

# 允许的安全占位符
SAFE_VALUES = {'0.0.0.0', '127.0.0.1', 'CHANGE_ME', 'YOUR_', 'your_', 'example.com', 'localhost'}

def scan_file(filepath: Path) -> list:
    """扫描单个文件，返回匹配的敏感信息"""
    if not filepath.exists():
        return []

    content = filepath.read_text(encoding='utf-8', errors='ignore')
    findings = []

    for name, pattern in PATTERNS.items():
        for match in re.finditer(pattern, content, re.IGNORECASE):
            matched_text = match.group()
            # 跳过安全占位符
            if any(safe in matched_text for safe in SAFE_VALUES):
                continue
            # 跳过注释中的示例
            line_start = content.rfind('\n', 0, match.start()) + 1
            line = content[line_start:content.find('\n', match.end())]
            if line.strip().startswith('#') or line.strip().startswith('//'):
                continue
            line_num = content[:match.start()].count('\n') + 1
            findings.append({
                'file': filepath.name,
                'line': line_num,
                'pattern': name,
                'match': matched_text,
                'context': line.strip()[:80]
            })

    return findings

def main():
    base = Path(__file__).parent
    all_findings = []

    print('=== 隐私信息扫描 ===\n')

    for fname in SCAN_FILES:
        filepath = base / fname
        if not filepath.exists():
            print(f'  [SKIP] {fname} (文件不存在)')
            continue

        findings = scan_file(filepath)
        if findings:
            all_findings.extend(findings)
            print(f'  [WARN] {fname}: 发现 {len(findings)} 处敏感信息')
            for f in findings:
                print(f'    L{f["line"]}: [{f["pattern"]}] {f["match"]}')
                print(f'           {f["context"]}')
        else:
            print(f'  [OK]   {fname}: 无敏感信息')

    print(f'\n=== 扫描结果 ===')
    print(f'扫描文件: {len(SCAN_FILES)}')
    print(f'发现问题: {len(all_findings)}')

    if all_findings:
        print('\n[FAIL] 发现敏感信息，请修复后再发布到 GitHub')
        sys.exit(1)
    else:
        print('\n[PASS] 未发现敏感信息，可以安全发布到 GitHub')
        sys.exit(0)

if __name__ == '__main__':
    main()
