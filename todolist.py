import tkinter as tk
from tkinter import ttk, messagebox
import requests
import datetime
import json

API_URL = "http://127.0.0.1:8000"

class TodoClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Todo AI Pro - 智能生活助手")
        self.root.geometry("1000x800")

        # 全局样式
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Big.TButton", font=("Helvetica", 12, "bold"))

        # === 核心状态 ===
        self.current_user_id = tk.StringVar(value="1") # 默认用户 ID 1
        self.current_location = tk.StringVar(value="🏠 家里") # 默认位置

        # === 布局：顶部栏 (用户 + 状态) ===
        self.setup_top_bar()

        # === 布局：主区域 (左右分栏) ===
        # PanedWindow 允许用户拖动中间的分隔线
        self.paned_window = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 左侧面板：操作区 (Todo List + 创建)
        self.left_panel = ttk.Frame(self.paned_window)
        self.paned_window.add(self.left_panel, weight=1)

        # 右侧面板：AI区 (预测 + 探索 + 搜索)
        self.right_panel = ttk.Frame(self.paned_window)
        self.paned_window.add(self.right_panel, weight=1)

        # === 初始化各个模块 ===
        self.setup_left_panel()
        self.setup_right_panel()
        self.load_history_tasks()

    def setup_top_bar(self):
        """顶部栏：用户切换 & 状态显示"""
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="👤 当前用户 ID:").pack(side=tk.LEFT)
        self.entry_user = ttk.Entry(top_frame, textvariable=self.current_user_id, width=5)
        self.entry_user.pack(side=tk.LEFT, padx=5)

        ttk.Label(top_frame, text="📍 当前位置:").pack(side=tk.LEFT, padx=(20, 0))
        # 虚拟地理位置选择
        loc_combo = ttk.Combobox(top_frame, textvariable=self.current_location, width=10, state="readonly")
        loc_combo['values'] = ("🏠 家里", "🏢 办公室", "💪 健身房", "☕ 咖啡厅", "🚇 地铁上")
        loc_combo.pack(side=tk.LEFT, padx=5)

        ttk.Button(top_frame, text="刷新系统状态", command=self.refresh_status).pack(side=tk.RIGHT)

    def setup_left_panel(self):
        """左侧：任务管理核心"""
        # 1. 创建任务区域
        frame_create = ttk.LabelFrame(self.left_panel, text="✍️ 新建任务 (时空上下文)", padding=10)
        frame_create.pack(fill=tk.X, pady=5)

        # 内容
        ttk.Label(frame_create, text="我想做...").grid(row=0, column=0, sticky="w")
        self.entry_content = ttk.Entry(frame_create, width=30)
        self.entry_content.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        # 时间 (自动填充)
        ttk.Label(frame_create, text="开始时间:").grid(row=1, column=0, sticky="w")
        self.entry_time = ttk.Entry(frame_create, width=30)
        self.entry_time.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        self.entry_time.insert(0, datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

        # 提交按钮
        btn_add = ttk.Button(frame_create, text="✅ 确认创建", style="Big.TButton", command=self.add_todo)
        btn_add.grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)

        # 2. 任务列表区域 (互动区)
        frame_list = ttk.LabelFrame(self.left_panel, text="📋 我的待办 (双击完成)", padding=10)
        frame_list.pack(fill=tk.BOTH, expand=True, pady=5)

        # 列表控件
        self.todo_tree = ttk.Treeview(frame_list, columns=("ID", "Content", "Time"), show="headings")
        self.todo_tree.heading("ID", text="ID")
        self.todo_tree.heading("Content", text="内容")
        self.todo_tree.heading("Time", text="时间")
        
        self.todo_tree.column("ID", width=40)
        self.todo_tree.column("Content", width=200)
        self.todo_tree.column("Time", width=120)

        self.todo_tree.pack(fill=tk.BOTH, expand=True)
        
        # 绑定双击事件 (模拟完成互动)
        self.todo_tree.bind("<Double-1>", self.on_complete_task)
        
        ttk.Label(frame_list, text="提示: 双击任务可标记为完成 (触发交互学习)").pack(side=tk.BOTTOM, anchor="w")

    def setup_right_panel(self):
        """右侧：AI 智能体"""
        # 1. 预测模块 (Target 2)
        frame_predict = ttk.LabelFrame(self.right_panel, text="🔮 AI 预测 (下一步做什么?)", padding=10)
        frame_predict.pack(fill=tk.X, pady=5)

        self.lbl_prediction = ttk.Label(frame_predict, text="等待行为触发...", font=("Arial", 10, "italic"), foreground="gray")
        self.lbl_prediction.pack(pady=10)
        btn_frame = ttk.Frame(frame_predict)
        btn_frame.pack(fill=tk.X)
        
        ttk.Button(btn_frame, text="⚙️ 训练模型", command=self.train_ai, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🧠 预测下一步", command=self.predict_next, width=15).pack(side=tk.LEFT, padx=2)

        ttk.Button(frame_predict, text="🧠 基于上一件事猜测", command=self.predict_next).pack(fill=tk.X)

        # 2. 探索模块 (Target 3)
        frame_trend = ttk.LabelFrame(self.right_panel, text="🔥 全网热榜 (Redis 驱动)", padding=10)
        frame_trend.pack(fill=tk.X, pady=5)

        self.trend_list = tk.Listbox(frame_trend, height=5)
        self.trend_list.pack(fill=tk.X, pady=5)
        
        ttk.Button(frame_trend, text="🔄 刷新热度", command=self.refresh_trending).pack(fill=tk.X)

        # 3. 搜索模块 (Target 1)
        frame_search = ttk.LabelFrame(self.right_panel, text="🔍 语义记忆检索", padding=10)
        frame_search.pack(fill=tk.BOTH, expand=True, pady=5)

        self.entry_query = ttk.Entry(frame_search)
        self.entry_query.pack(fill=tk.X, pady=5)
        self.entry_query.insert(0, "找一下之前玩游戏的记录")

        ttk.Button(frame_search, text="搜索", command=self.search_todos).pack(fill=tk.X)
        
        self.search_tree = ttk.Treeview(frame_search, columns=("Score", "Content"), show="headings", height=5)
        self.search_tree.heading("Score", text="相似度")
        self.search_tree.heading("Content", text="内容")
        self.search_tree.column("Score", width=60)
        self.search_tree.pack(fill=tk.BOTH, expand=True, pady=5)

    # === logical function ===
    def train_ai(self):
        """调用后端训练接口"""
        try:
            self.lbl_prediction.config(text="正在训练大脑...", foreground="orange")
            self.root.update() # force UI refresh
            
            response = requests.post(f"{API_URL}/train/")
            data = response.json()
            
            if data.get("status") == "success":
                messagebox.showinfo("训练完成", f"AI 已根据你的历史数据进化！\n\n{data.get('message')}")
                self.lbl_prediction.config(text="模型已就绪 (Ready)", foreground="green")
            else:
                messagebox.showwarning("训练未完成", data.get("message"))
                self.lbl_prediction.config(text="训练失败", foreground="red")
                
        except Exception as e:
            messagebox.showerror("错误", str(e))
            self.lbl_prediction.config(text="连接失败", foreground="red")

    def add_todo(self):
        """创建任务"""
        content = self.entry_content.get()
        start_time = self.entry_time.get()
        location = self.current_location.get() # get fake location
        user_id = self.current_user_id.get()

        if not content:
            messagebox.showwarning("提示", "内容不能为空")
            return

        # 在内容里自动附带位置信息 (模拟时空上下文)
        # 因为后端还没有 location 字段，我们把它拼在内容里，方便语义理解
        full_content = f"[{location}] {content}"

        payload = {
            "content": full_content,
            "start_time": start_time
        }

        try:
            response = requests.post(f"{API_URL}/todos/", json=payload)
            if response.status_code == 200:
                # 添加成功后，自动添加到左侧列表
                data = response.json()
                self.todo_tree.insert("", 0, values=(data['id'], data['content'], data['start_time']))
                self.entry_content.delete(0, tk.END)
                
                # 联动：添加完任务后，自动预测下一步
                self.predict_next(last_content=content)
            else:
                messagebox.showerror("错误", response.text)
        except Exception as e:
            messagebox.showerror("连接失败", str(e))

    def on_complete_task(self, event):
        """双击完成任务 -> 调用后端删除接口"""
        selection = self.todo_tree.selection()
        if not selection:
            return

        item = selection[0]
        values = self.todo_tree.item(item, "values")
        task_id = values[0] # 获取 ID
        task_content = values[1]
        
        # 弹窗确认
        confirm = messagebox.askyesno("完成任务", f"确认完成并删除任务吗？\n\n{task_content}")
        
        if confirm:
            try:
                # 发送 DELETE 请求
                response = requests.delete(f"{API_URL}/todos/{task_id}")
                
                if response.status_code == 200:
                    # UI 移除
                    self.todo_tree.delete(item)
                    
                    # 交互反馈
                    self.lbl_prediction.config(text=f"已完成: {task_content}", foreground="green")
                    
                    # 自动触发一次小预测 (基于刚刚完成的事)
                    self.predict_next(last_content=task_content)
                else:
                    messagebox.showerror("删除失败", f"后端返回: {response.text}")
                    
            except Exception as e:
                messagebox.showerror("连接错误", str(e))

    def predict_next(self, last_content=None):
        """调用预测接口"""
        # 如果没有传内容，就用输入框里的
        if not last_content:
            last_content = self.entry_content.get()
            if not last_content:
                last_content = "发呆" # 默认状态
        
        payload = {
            "content": last_content,
            "start_time": datetime.datetime.now().isoformat()
        }
        
        try:
            response = requests.post(f"{API_URL}/predict/", json=payload)
            if response.status_code == 200:
                result = response.json().get("result", "未知")
                # 更新 UI
                self.lbl_prediction.config(text=f"👉 {result}", foreground="blue")
            else:
                self.lbl_prediction.config(text="预测失败", foreground="red")
        except:
            self.lbl_prediction.config(text="AI 离线中...", foreground="red")

    def refresh_trending(self):
        """刷新热度榜"""
        try:
            response = requests.get(f"{API_URL}/explore/trending")
            if response.status_code == 200:
                data = response.json()
                items = data.get("list", [])
                
                self.trend_list.delete(0, tk.END)
                for item in items:
                    # 格式: 1. 喝奶茶 (🔥 50)
                    text = f"{item['rank']}. {item['content']} (🔥 {item['hot_index']})"
                    self.trend_list.insert(tk.END, text)
        except Exception as e:
            print(e)

    def search_todos(self):
        """搜索逻辑 (修复 422 错误版)"""
        query = self.entry_query.get()
        if not query:
            messagebox.showwarning("提示", "请输入搜索内容")
            return

        # 补全后端需要的 start_time 和 end_time
        # 默认范围：从 1970年 到 现在+1年 (涵盖所有)
        now = datetime.datetime.now()
        start_default = "1970-01-01T00:00:00"
        end_default = (now + datetime.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")

        payload = {
            "query": query,
            "top_k": 3,
            "start_time": start_default,
            "end_time": end_default
        }

        try:
            #clean previous results
            for item in self.search_tree.get_children():
                self.search_tree.delete(item)
                
            response = requests.post(f"{API_URL}/search/", json=payload)
            
            if response.status_code == 200:
                raw_data = response.json()
                
                #兼容list/dict解析
                tasks = []
                if isinstance(raw_data, list): 
                    tasks = raw_data
                elif isinstance(raw_data, dict): 
                    tasks = raw_data.get("results", [])
                
                for t in tasks:
                    # 兼容 C++ list [id, score, content] 和 dict {"similarity":...}
                    if isinstance(t, list) and len(t) >= 3:
                        # t[1] score, t[2] content
                        score = round(float(t[1]), 4)
                        content = t[2]
                        self.search_tree.insert("", "end", values=(score, content))
                    elif isinstance(t, dict):
                        score = t.get("similarity", 0)
                        content = t.get("content", "未知")
                        self.search_tree.insert("", "end", values=(score, content))
            else:
                # 打印出具体缺了什么字段，方便调试
                print(f"❌ 后端拒绝 (422): {response.text}")
                messagebox.showerror("搜索失败", f"参数错误 (422):\n后端需要完整的时间范围参数")
                
        except Exception as e:
            messagebox.showerror("Search Error", str(e))

    def refresh_status(self):
        """刷新所有数据"""
        self.refresh_trending()
        messagebox.showinfo("系统", "状态已刷新")
        
    def load_history_tasks(self):
        """从后端加载历史记录"""
        try:
            # 调用刚才写的 GET /todos/ 接口
            response = requests.get(f"{API_URL}/todos/")
            
            if response.status_code == 200:
                tasks = response.json()
                # 清空现有列表
                for item in self.todo_tree.get_children():
                    self.todo_tree.delete(item)
                
                # 填充数据
                for task in tasks:
                    # 这里的字段名要和 schemas.TodoResponse 一致
                    t_id = task.get('id')
                    t_content = task.get('content')
                    t_time = task.get('start_time')
                    
                    # 插入到列表 (index='end' 表示追加到底部)
                    self.todo_tree.insert("", "end", values=(t_id, t_content, t_time))
                    
                print(f"DEBUG: 成功加载了 {len(tasks)} 条历史任务")
            else:
                print("后端无数据或连接失败")
                
        except Exception as e:
            print(f"无法加载历史记录: {e}")
            # 不弹窗报错，以免影响用户打开软件的体验，只在后台输出

if __name__ == "__main__":
    root = tk.Tk()
    app = TodoClientApp(root)
    root.mainloop()