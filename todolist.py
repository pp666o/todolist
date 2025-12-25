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
        self.root.geometry("1100x850") 

        # 全局样式
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Big.TButton", font=("Helvetica", 12, "bold"))

        # === 核心状态 ===
        self.current_user_id = tk.StringVar(value="1") # 默认用户 ID 1
        self.current_location = tk.StringVar(value="🏠 家里") # 默认位置
        
        self.market_data_map = {}
        self.ad_payload_map = {}   # 广告数据

        # === 布局：顶部栏 (用户 + 状ß态) ===
        self.setup_top_bar()
        ttk.Button(self.top_frame, text="👮 审核后台", command=self.open_admin_panel).pack(side=tk.RIGHT, padx=5)

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

        # === initialize sub-panels ===
        self.setup_left_panel()
        self.setup_right_panel()
        self.load_history_tasks()

    def setup_top_bar(self):
        """顶部栏：用户切换 & 状态显示"""
        self.top_frame = ttk.Frame(self.root, padding=10)
        self.top_frame.pack(fill=tk.X)

        ttk.Label(self.top_frame, text="👤 当前用户 ID:").pack(side=tk.LEFT)
        self.entry_user = ttk.Entry(self.top_frame, textvariable=self.current_user_id, width=5)
        self.entry_user.pack(side=tk.LEFT, padx=5)

        ttk.Label(self.top_frame, text="📍 当前位置:").pack(side=tk.LEFT, padx=(20, 0))
        # 虚拟地理位置选择
        loc_combo = ttk.Combobox(self.top_frame, textvariable=self.current_location, width=10, state="readonly")
        loc_combo['values'] = ("🏠 家里", "🏢 办公室", "💪 健身房", "☕ 咖啡厅", "🚇 地铁上")
        loc_combo.pack(side=tk.LEFT, padx=5)

        ttk.Button(self.top_frame, text="刷新系统状态", command=self.refresh_status).pack(side=tk.RIGHT)

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
        self.todo_tree.tag_configure('ad', foreground='blue', background='#e3f2fd') #AD styleß
        
        # 绑定双击事件 (模拟互动)
        self.todo_tree.bind("<Double-1>", self.on_complete_task)
        
        ttk.Label(frame_list, text="提示: 双击任务可标记为完成 (触发交互学习)").pack(side=tk.BOTTOM, anchor="w")

    def setup_right_panel(self):
       # 1. MAB 资产看板
        frame_asset = ttk.LabelFrame(self.right_panel, text="💰 MAB 资产 (Target 4)", padding=10)
        frame_asset.pack(fill=tk.X, pady=5)

        self.lbl_balance = ttk.Label(frame_asset, text="余额: 查询中...", font=("Arial", 12, "bold"), foreground="green")
        self.lbl_balance.pack(side=tk.LEFT)

        ttk.Button(frame_asset, text="⛏️ 挖矿 (+100)", command=self.mine_mab).pack(side=tk.RIGHT)
        ttk.Button(frame_asset, text="🔄 刷新", command=self.refresh_balance).pack(side=tk.RIGHT, padx=5)

        # 2. 竞价发布区
        frame_bid = ttk.LabelFrame(self.right_panel, text="📢 发布合拍 (RTB竞价)", padding=10)
        frame_bid.pack(fill=tk.X, pady=5)

        ttk.Label(frame_bid, text="内容:").pack(side=tk.LEFT)
        self.entry_bid_content = ttk.Entry(frame_bid, width=12)
        self.entry_bid_content.pack(side=tk.LEFT, padx=5)

        ttk.Label(frame_bid, text="出价:").pack(side=tk.LEFT)
        self.entry_bid_price = ttk.Entry(frame_bid, width=5)
        self.entry_bid_price.pack(side=tk.LEFT, padx=5)
        self.entry_bid_price.insert(0, "50")

        ttk.Button(frame_bid, text="🚀 上架", command=self.submit_bid).pack(side=tk.LEFT, padx=5)

        # 3. 交易大厅 (撮合区)
        frame_market = ttk.LabelFrame(self.right_panel, text="📊 实时合拍市场 (Target 4)", padding=10)
        frame_market.pack(fill=tk.BOTH, expand=True, pady=5)

        btn_bar = ttk.Frame(frame_market)
        btn_bar.pack(fill=tk.X, pady=2)
        ttk.Button(btn_bar, text="🔄 刷新市场", command=self.refresh_market).pack(side=tk.LEFT)
        #合拍按钮
        ttk.Button(btn_bar, text="🤝 立即合拍 (赚MAB)", command=self.accept_order).pack(side=tk.RIGHT)

        self.market_list = ttk.Treeview(frame_market, columns=("Bid", "User", "Content"), show="headings", height=6)
        self.market_list.heading("Bid", text="赏金")
        self.market_list.heading("User", text="金主")
        self.market_list.heading("Content", text="内容")
        self.market_list.column("Bid", width=50, anchor="center")
        self.market_list.column("User", width=50, anchor="center")
        self.market_list.column("Content", width=120)
        self.market_list.pack(fill=tk.BOTH, expand=True)

        # 4. 预测模块 (节省空间)
        frame_predict = ttk.LabelFrame(self.right_panel, text="🔮 AI 预测", padding=5)
        frame_predict.pack(fill=tk.X, pady=5)

        self.lbl_prediction = ttk.Label(frame_predict, text="等待预测...", font=("Arial", 10, "italic"), foreground="gray")
        self.lbl_prediction.pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_predict, text="🧠 预测下一步", command=self.predict_next).pack(side=tk.RIGHT)

        # 5. 全网热榜 (Redis)
        frame_trend = ttk.LabelFrame(self.right_panel, text="🔥 全网热榜", padding=5)
        frame_trend.pack(fill=tk.X, pady=5)
        
        self.trend_list = tk.Listbox(frame_trend, height=4)
        self.trend_list.pack(fill=tk.X)
        ttk.Button(frame_trend, text="🔄 刷新热度", command=self.refresh_trending).pack(fill=tk.X)

        # 初始化加载 Target 4 数据
        self.refresh_balance()
        self.refresh_market()
        self.refresh_trending()
    def open_admin_panel(self):
        """打开管理员审核窗口"""
        win = tk.Toplevel(self.root)
        win.title("管理员审核后台 (Target 5)")
        win.geometry("600x400")
        
        lbl = ttk.Label(win, text="待审核广告队列", font=("Arial", 12, "bold"))
        lbl.pack(pady=10)
        
        # listview
        columns = ("content", "bid", "user", "raw")
        tree = ttk.Treeview(win, columns=columns, show="headings")
        tree.heading("content", text="内容")
        tree.heading("bid", text="出价")
        tree.heading("user", text="用户")
        tree.column("content", width=200)
        tree.column("bid", width=50)
        tree.column("user", width=50)
        # 隐藏 raw 列
        tree.column("raw", width=0, stretch=False)
        
        tree.pack(fill=tk.BOTH, expand=True, padx=10)
        
        def load_data():
            for i in tree.get_children(): tree.delete(i)
            try:
                # 调用在后端写的 /admin/pending/ api
                res = requests.get(f"{API_URL}/admin/pending/")
                items = res.json().get("pending", [])
                for item in items:
                    # make raw payload string 用于提交
                    raw = json.dumps(item)
                    tree.insert("", "end", values=(item['content'], item['bid'], item['sponsor'], raw))
            except Exception as e:
                print(f"加载审核列表失败: {e}")

        def audit(action):
            sel = tree.selection()
            if not sel: return
            raw = tree.item(sel[0], "values")[3] # 取出隐藏的 raw 数据
            
            try:
                # get/post audit API
                requests.post(f"{API_URL}/admin/audit/", json={"raw_payload": raw, "action": action})
                load_data() # refresh
                messagebox.showinfo("操作成功", f"已{action}")
            except Exception as e:
                messagebox.showerror("错误", str(e))

        # 按钮区
        btn_frame = ttk.Frame(win, padding=10)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="✅ 批准上架", command=lambda: audit("approve")).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="❌ 拒绝驳回", command=lambda: audit("reject")).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="🔄 刷新", command=load_data).pack(side=tk.RIGHT)
        
        load_data()
    # === logical function ===
    def refresh_balance(self):
        """刷新余额 (增加错误显示)"""
        user_id = self.current_user_id.get()
        try:
            res = requests.get(f"{API_URL}/mab/balance/{user_id}")
            
            if res.status_code == 200:
                # 成功情况
                bal = res.json().get("balance", 0)
                self.lbl_balance.config(text=f"余额: {bal} MAB", foreground="green")
            else:
                # new：如果接口报错 (比如 404 或 500)，直接显示在界面上
                self.lbl_balance.config(text=f"余额: 异常 ({res.status_code})", foreground="red")
                
        except Exception as e:
            # 网络连不上
            self.lbl_balance.config(text="余额: 连接断开", foreground="red")
            print(f"Debug: {e}")

    def mine_mab(self):
        """挖矿"""
        user_id = self.current_user_id.get()
        try:
            requests.post(f"{API_URL}/mab/faucet/", json={"user_id": user_id, "amount": 100})
            self.refresh_balance()
            messagebox.showinfo("成功", "挖矿成功！+100 MAB")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def submit_bid(self):
        """发布竞价"""
        user_id = self.current_user_id.get()
        content = self.entry_bid_content.get()
        price = self.entry_bid_price.get()

        if not content or not price.isdigit():
            messagebox.showwarning("提示", "请输入内容和有效出价")
            return

        try:
            payload = {"user_id": user_id, "content": content, "bid_amount": int(price)}
            res = requests.post(f"{API_URL}/exchange/bid/", json=payload)
            if res.status_code == 200:
                messagebox.showinfo("成功", "竞价单已发布！")
                self.entry_bid_content.delete(0, tk.END)
                self.refresh_balance()
                self.refresh_market()
            else:
                messagebox.showerror("失败", res.json().get("detail", "未知错误"))
        except Exception as e:
            messagebox.showerror("连接失败", str(e))

    def refresh_market(self):
        """刷新市场列表 (修复后)"""
        try:
            # 1. 清空 UI 列表
            for item in self.market_list.get_children():
                self.market_list.delete(item)
            
            # 2. 清空数据缓存 (现在 self.market_data_map 已经定义了，不会报错了)
            self.market_data_map.clear()
            
            # 3. 请求后端
            print("正在请求市场数据...") # Debug
            res = requests.get(f"{API_URL}/exchange/board/")
            
            if res.status_code == 200:
                data = res.json()
                # 优先读取 list，如果没有则读取 market (兼容旧代码)
                orders = data.get("list") or data.get("market") or []
                
                print(f"获取到 {len(orders)} 条订单") # Debug
                
                for order in orders:
                    # 安全获取字段，防止 Key 报错
                    bid_price = order.get('bid', order.get('amount', 0))
                    sponsor = order.get('sponsor', order.get('user_id', 'Unknown'))
                    content = order.get('content', '无内容')
                    raw_data = order.get('_raw', '{}')
                    
                    # 插入 UI
                    item_id = self.market_list.insert("", "end", values=(
                        f"{bid_price}", 
                        f"ID:{sponsor}", 
                        content
                    ))
                    
                    # 缓存原始数据
                    self.market_data_map[item_id] = raw_data
            else:
                print(f"市场刷新失败: {res.status_code}")
                
        except Exception as e:
            # [关键] 打印出具体的错误，而不是 pass 掉
            print(f"❌ 渲染市场列表出错: {e}")
            messagebox.showerror("系统错误", f"无法刷新市场: {e}")

    def accept_order(self):
        """接单合拍"""
        selection = self.market_list.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一个订单")
            return
            
        item_id = selection[0]
        raw_payload = self.market_data_map.get(item_id)
        current_user = self.current_user_id.get()
        
        if not raw_payload: return

        try:
            payload = {"worker_id": current_user, "raw_payload": raw_payload}
            res = requests.post(f"{API_URL}/exchange/accept/", json=payload)
            
            if res.status_code == 200:
                data = res.json()
                messagebox.showinfo("恭喜", data.get("msg"))
                self.refresh_balance()
                self.refresh_market()
            else:
                messagebox.showerror("失败", res.json().get("detail", "手慢了或出错了"))
        except Exception as e:
            messagebox.showerror("错误", str(e))
    
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
        # 因为后端还没有 location 字段，我就把它拼在内容里，方便语义理解
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
        """
        双击事件处理 (Target 5: 区分 任务完成 vs 广告接单)
        """
        selection = self.todo_tree.selection()
        if not selection: return

        item = selection[0]
        values = self.todo_tree.item(item, "values")
        task_id = str(values[0])
        content = values[1]
        
        # === Branch A: if ad ===
        if task_id in self.ad_payload_map:
            confirm = messagebox.askyesno("接单机会", f"这是一个推荐广告任务！\n\n{content}\n\n是否立即接单赚钱？")
            if confirm:
                # 调用接单逻辑
                raw_payload = self.ad_payload_map[task_id]
                self.perform_accept_order(raw_payload)
            return

        # === Branch B: if normal task ===
        confirm = messagebox.askyesno("完成任务", f"确认完成并删除任务吗？\n\n{content}")
        if confirm:
            self.delete_normal_task(task_id, item)

    def perform_accept_order(self, raw_payload):
        """执行接单 (复用逻辑)"""
        current_user = self.current_user_id.get()
        try:
            payload = {"worker_id": current_user, "raw_payload": raw_payload}
            res = requests.post(f"{API_URL}/exchange/accept/", json=payload)
            
            if res.status_code == 200:
                data = res.json()
                messagebox.showinfo("恭喜", data.get("msg"))
                self.refresh_balance()
                self.load_history_tasks() # 刷新列表，广告可能会消失
            else:
                messagebox.showerror("失败", res.json().get("detail", "接单失败"))
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def delete_normal_task(self, task_id, item_ui):
        """执行删除普通任务"""
        try:
            requests.delete(f"{API_URL}/todos/{task_id}")
            self.todo_tree.delete(item_ui)
            self.predict_next() # 触发一次预测
        except Exception as e:
            print(f"删除失败: {e}")

    def predict_next(self, last_content=None):
        """调用预测接口"""
        # if there's no last_content, use the entry box
        if not last_content:
            last_content = self.entry_content.get()
            if not last_content:
                last_content = "发呆" # defalut status
        
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
            # fix 3：修改 URL 为 /trending/ (对应 endpoints.py)
            response = requests.get(f"{API_URL}/trending/")
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("list", [])
                
                # 使用 self.trend_list
                self.trend_list.delete(0, tk.END)
                
                if not items:
                    self.trend_list.insert(tk.END, "暂无热度数据...")

                for item in items:
                    # 格式: 1. 喝奶茶 (🔥 50)
                    text = f"{item['rank']}. {item['content']} (🔥 {item['hot_index']})"
                    self.trend_list.insert(tk.END, text)
            else:
                print(f"热榜刷新失败: {response.status_code}")
                
        except Exception as e:
            print(f"热榜错误: {e}")

    def search_todos(self):
        """搜索逻辑 (修复 422 错误)"""
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
                #调试
                print(f"❌ 后端拒绝 (422): {response.text}")
                messagebox.showerror("搜索失败", f"参数错误 (422):\n后端需要完整的时间范围参数")
                
        except Exception as e:
            messagebox.showerror("Search Error", str(e))

    def refresh_status(self):
        """刷新所有数据"""
        self.refresh_trending()
        messagebox.showinfo("系统", "状态已刷新")
        
    def load_history_tasks(self):
        """加载历史任务 (Target 5: 渲染混入的广告)"""
        try:
            # clear cache
            self.ad_payload_map.clear()
            
            response = requests.get(f"{API_URL}/todos/")
            
            if response.status_code == 200:
                tasks = response.json()
                # clear UI
                for item in self.todo_tree.get_children():
                    self.todo_tree.delete(item)
                
                for task in tasks:
                    t_id = task.get('id')
                    t_content = task.get('content')
                    t_time = task.get('start_time')
                    is_ad = task.get('is_ad', False) # get ad flag
                    
                    if is_ad:
                        #如果是广告：
                        # 1. 存入 payload 方便点击时调用
                        self.ad_payload_map[str(t_id)] = task.get('ad_payload')
                        # 2. 插入时带上 'ad' 标签 -> 变色
                        self.todo_tree.insert("", "end", values=(t_id, t_content, "📢 推广"), tags=('ad',))
                    else:
                        # 普通任务
                        self.todo_tree.insert("", "end", values=(t_id, t_content, t_time))
                    
                print(f"DEBUG: 加载完成，含广告: {len(self.ad_payload_map)} 条")
            else:
                print("后端无数据")
                
        except Exception as e:
            print(f"无法加载历史: {e}")
            
if __name__ == "__main__":
    root = tk.Tk()
    app = TodoClientApp(root)
    root.mainloop()