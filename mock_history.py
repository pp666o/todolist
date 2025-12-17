import random
import datetime
from sqlalchemy.orm import Session
from app import models, database, utils

def generate_mock_data():
    db = database.SessionLocal()
    
    # 1. CLEAR existing data(if any)
    print(">>> 正在清空数据库...")
    db.query(models.Interaction).delete()
    db.query(models.Todo).delete()
    db.commit()
    
    print(">>> 正在生成'强逻辑'的训练数据...")
    
    start_date = datetime.datetime.now() - datetime.timedelta(days=30)
    
    # === Define strong chain ===
    # Chain A (Working flow): 写C++ -> 修复Bug -> 部署服务器 -> 和Vivian开会
    chain_work = ["编写C++模块", "修复Python Bug", "部署服务器", "和Vivian开会"]
    
    # Chain B (Healthy flow): 去健身房举铁 -> 喝蛋白粉 -> 吃轻食沙拉
    chain_health = ["去健身房举铁", "喝蛋白粉", "吃轻食沙拉"]
    
    # Chain C (entertainment flow): 玩Minecraft -> 看Netflix电影 -> 睡觉
    chain_fun = ["玩Minecraft", "看Netflix电影", "睡觉"]

    for day_offset in range(30):
        current_date = start_date + datetime.timedelta(days=day_offset)
        
        #保证顺序固定
        daily_chains = [chain_work, chain_health, chain_fun]
        selected_chain = random.choice(daily_chains)
        
        # 偶尔混入一些跨链条的任务，增加多样性
        if random.random() > 0.7:
             selected_chain = chain_work + chain_health
        
        base_hour = 9
        for i, task_content in enumerate(selected_chain):
            # 1. Create Todo
            task_time = current_date.replace(hour=base_hour + i, minute=0)
            
            vector = utils.get_embedding(task_content)
            
            todo = models.Todo(
                content=task_content,
                start_time=task_time,
                embedding=vector
            )
            db.add(todo)
            db.commit()
            db.refresh(todo)
            
            # 2.record Interaction (complete)
            interact_time = task_time + datetime.timedelta(minutes=30)
            
            interaction = models.Interaction(
                user_id=1,
                todo_id=todo.id,
                action_type="complete",
                day_of_week=current_date.weekday(),
                hour_of_day=interact_time.hour,
                timestamp=interact_time
            )
            db.add(interaction)
    
    db.commit()
    print(">>> ✅ 数据生成完毕！因果关系已植入。")

if __name__ == "__main__":
    generate_mock_data()