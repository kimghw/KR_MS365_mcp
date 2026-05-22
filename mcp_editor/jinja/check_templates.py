#!/usr/bin/env python3
import os

templates = {
    'server_rest.jinja2': {
        'checks': [
            ('파라미터 파싱', 'data.get("name")', True),
            ('params 사용 안함', 'data.get("params"', False),
        ]
    },
    'server_stdio.jinja2': {
        'checks': [
            ('초기화 코드', 'Initialize services', True),
            ('서비스 초기화 루프', 'for key, service_info in unique_services.items()', True),
            ('initialize 메서드 호출', '.initialize()', True),
        ]
    },
    'server_stream.jinja2': {
        'checks': [
            ('초기화 코드', 'Initialize services', True),
            ('서비스 초기화 루프', 'for key, service_info in unique_services.items()', True),
            ('initialize 메서드 호출', '.initialize()', True),
            ('on_startup 메서드', 'async def on_startup', True),
        ]
    }
}

print("=" * 60)
print("템플릿 파일 수정 상태 검증")
print("=" * 60)

for filename, checks in templates.items():
    print(f"\n[FILE] {filename}")
    print("-" * 40)
    
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            content = f.read()
        
        all_passed = True
        for check_name, pattern, should_exist in checks['checks']:
            exists = pattern in content
            if exists == should_exist:
                print(f"  [OK] {check_name}: {'있음' if exists else '없음'} (정상)")
            else:
                print(f"  [ERROR] {check_name}: {'있음' if exists else '없음'} (오류)")
                all_passed = False
        
        if all_passed:
            print(f"  [OK] {filename} 완벽하게 수정됨!")
    else:
        print(f"  [ERROR] 파일이 존재하지 않음")

print("\n" + "=" * 60)
print("최종 결과")
print("=" * 60)

# 파일 수정 시간 확인
import datetime
for filename in templates.keys():
    if os.path.exists(filename):
        mtime = os.path.getmtime(filename)
        mod_time = datetime.datetime.fromtimestamp(mtime)
        print(f"  {filename}: 수정 시간 {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")

