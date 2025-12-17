import tkinter as tk
from tkinter import ttk, messagebox
import requests
import datetime
import json

API_URL = "http://127.0.0.1:8000"

class TodoClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Todo AI 客户端 (Target 1 Demo)")
        self.root.geometry("600x700")

        style = ttk.Style()
        style.theme_use('clam')

        # === Moudle 1: add task ===
        self.frame_add = ttk.LabelFrame(root, text="📝 创建新任务 (写入 PostgreSQL + C++ Engine)", padding=10)
        self.frame_add.pack(fill="x", padx=10, pady=5)

        ttk.Label(self.frame_add, text="任务内容:").grid(row=0, column=0, sticky="w")
        self.entry_content = ttk.Entry(self.frame_add, width=40)
        self.entry_content.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(self.frame_add, text="开始时间:").grid(row=1, column=0, sticky="w")
        self.entry_time = ttk.Entry(self.frame_add, width=40)
        self.entry_time.grid(row=1, column=1, padx=5, pady=5)
        #default to now
        self.entry_time.insert(0, datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

        self.btn_add = ttk.Button(self.frame_add, text="提交任务", command=self.add_todo)
        self.btn_add.grid(row=2, column=1, sticky="e", pady=10)

        # === Moudle 2: search tasks ===
        self.frame_search = ttk.LabelFrame(root, text="🔍 语义搜索 (调用 C++ 向量检索)", padding=10)
        self.frame_search.pack(fill="both", expand=True, padx=10, pady=5)

        # input fields
        ttk.Label(self.frame_search, text="模糊意图:").grid(row=0, column=0, sticky="w")
        self.entry_query = ttk.Entry(self.frame_search, width=40)
        self.entry_query.grid(row=0, column=1, padx=5, pady=5)
        self.entry_query.insert(0, "我想找人吃饭") #default query

        #time range - start
        ttk.Label(self.frame_search, text="范围开始:").grid(row=1, column=0, sticky="w")
        self.entry_start = ttk.Entry(self.frame_search, width=40)
        self.entry_start.grid(row=1, column=1, padx=5, pady=5)
        #default to today 00:00
        today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S")
        self.entry_start.insert(0, today_start)

        #time range - end
        ttk.Label(self.frame_search, text="范围结束:").grid(row=2, column=0, sticky="w")
        self.entry_end = ttk.Entry(self.frame_search, width=40)
        self.entry_end.grid(row=2, column=1, padx=5, pady=5)
        #default to today 23:59
        today_end = datetime.datetime.now().replace(hour=23, minute=59, second=59).strftime("%Y-%m-%dT%H:%M:%S")
        self.entry_end.insert(0, today_end)

        self.btn_search = ttk.Button(self.frame_search, text="开始匹配", command=self.search_todos)
        self.btn_search.grid(row=3, column=1, sticky="e", pady=10)

        #Treeview
        self.tree = ttk.Treeview(self.frame_search, columns=("ID", "Score", "Content"), show="headings", height=15)
        self.tree.heading("ID", text="ID")
        self.tree.heading("Score", text="匹配度")
        self.tree.heading("Content", text="原始内容")
        
        self.tree.column("ID", width=50)
        self.tree.column("Score", width=80)
        self.tree.column("Content", width=350)
        
        self.tree.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=10)

    def add_todo(self):
        """发送 POST /todos/ 请求"""
        content = self.entry_content.get()
        start_time = self.entry_time.get()

        if not content:
            messagebox.showwarning("提示", "请输入任务内容")
            return

        payload = {
            "content": content,
            "start_time": start_time
        }

        try:
            response = requests.post(f"{API_URL}/todos/", json=payload)
            if response.status_code == 200:
                messagebox.showinfo("成功", "✅ 任务已创建，向量已同步至 C++ 引擎！")
                self.entry_content.delete(0, tk.END) #clear input
            else:
                messagebox.showerror("错误", f"服务器报错: {response.text}")
        except Exception as e:
            messagebox.showerror("连接失败", f"无法连接到后端，请确保 main.py 正在运行。\n错误: {e}")

    def search_todos(self):
        """发送 POST /search/ 请求"""
        query = self.entry_query.get()
        start_time = self.entry_start.get()
        end_time = self.entry_end.get()

        if not query:
            messagebox.showwarning("提示", "请输入搜索意图")
            return

        #clear previous results
        for item in self.tree.get_children():
            self.tree.delete(item)

        payload = {
            "query": query,
            "start_time": start_time,
            "end_time": end_time,
            "top_k": 5
        }

        try:
            response = requests.post(f"{API_URL}/search/", json=payload)
            if response.status_code == 200:
                results = response.json()
                
                if not results:
                    messagebox.showinfo("结果", "🤔 在该时间范围内没有找到相关任务。")
                    return

                #fill treeview
                for item in results:
                    #keep 4 decimal places for score
                    score_display = f"{item['score']:.4f}" if item['score'] else "N/A"
                    self.tree.insert("", tk.END, values=(item['id'], score_display, item['content']))
            else:
                messagebox.showerror("错误", f"搜索失败: {response.text}")
        except Exception as e:
            messagebox.showerror("连接失败", f"无法连接到后端。\n错误: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = TodoClientApp(root)
    root.mainloop()