import re
import json

def parse_plan_text(text: str) -> list[dict]:
    plan_data = []
    
    # 1. Попытка JSON
    try:
        clean_json = text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for key, val in item.items():
                        # Ищем цифру в ключе (Пост 1, День 1, Post 1)
                        num_match = re.search(r'\d+', key)
                        if num_match:
                            clean_topic = re.sub(r'<[^>]+>', '', val).strip()
                            plan_data.append({"day": int(num_match.group()), "topic": clean_topic})
            if plan_data: return plan_data
    except json.JSONDecodeError:
        pass

    # 2. Построчный Regex
    lines = text.split('\n')
    for line in lines:
        line = line.replace('*', '') 
        clean_line = line.strip('[]{},"\' ')
        
        if not clean_line: continue
        
        # Ищем: (Пост|День|Post) (Цифра) (Разделитель) (Текст)
        match = re.search(r'(?:Пост|Post|День|Day)?\s*(\d+)[-:.)]\s*(.+)', clean_line, re.IGNORECASE)
        
        if match:
            num = int(match.group(1))
            raw_topic = match.group(2)
            topic_cleaned = re.sub(r'<[^>]+>', '', raw_topic).strip(' ",')
            
            plan_data.append({
                "day": num, # Используем поле day_number в базе как порядковый номер поста
                "topic": topic_cleaned
            })
            
    return plan_data