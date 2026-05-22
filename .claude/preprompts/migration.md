1. 현재 프로젝트의 구조는 일반서버가 있고, mcp 웹에디터를 이용해서 일반서버를 mcp  서버로 업데이트 하는거야. 주요 기능은  mcp서버 생성 및 변경, 툴생성및 변경, 인자 생성 및 변경등임

2. 현재 프로젝트는 파이썬을 기본으로 구성되어 있어. 대상 프로젝트도 파이썬이고, 웹에디터도 파이써닝야. 웹에디터가 현재 파이썬 서버 대상인거지. 2개 서버가 서로 독립적이지만  데코레이터와 ast가 연결되어 있어.
-(중요  ) 현재 작업 목적은 일반 프로젝트 구성을 java로 변경하는거야. 웹에디터는 그대로 파이썬을 이용할 거고, 웹에디터에서 생성하는 스크립트 또한 java 스크립트가 주요 할거야.

3. 웹에디터에서의 대략적인 구조는 /home/kimghw/Connector_auth/.claude/preprompts/web_dataflow.md  이것과 같음 

4. 그럼 변경해아할 파일들은 대략적으로 다음과 같음. 물론 웹에디터를 전반적으로 수정할 부분이 많겠지만. 다음의 내용들도 참고/수정해야할거 같아. 
/home/kimghw/Connector_auth/.claude/commands
/home/kimghw/Connector_auth/.claude/commands/mcp_service.md
/home/kimghw/Connector_auth/.claude/commands/handler.md
/home/kimghw/Connector_auth/.claude/commands/terminology.md
/home/kimghw/Connector_auth/.claude/commands/tool_definition_guide.md
/home/kimghw/Connector_auth/.claude/preprompts/add_config.md
/home/kimghw/Connector_auth/.claude/preprompts/web_dataflow.md
/home/kimghw/Connector_auth/.claude/skills

5. 