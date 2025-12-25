import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sqlalchemy.orm import Session
from app import models
import os
import pickle
from collections import defaultdict
import jieba

class BehaviorModel:
    def __init__(self):
        self.kmeans = None
        self.transition_matrix = None 
        self.cluster_map = {} 
        self.n_clusters = 10

    def train(self, db: Session, user_id: int):
        print(f">>> [ML] 正在为用户 {user_id} 训练模型...")
        
        # 1. get user interactions
        results = db.query(models.Interaction, models.Todo).join(
            models.Todo, models.Interaction.todo_id == models.Todo.id
        ).filter(
            models.Interaction.user_id == user_id,
            models.Interaction.action_type == "complete"
        ).order_by(models.Interaction.timestamp.asc()).all()
        
        if len(results) < 10:
            print(">>> [ML] 数据过少，跳过训练。")
            return "No Data"

        # 2. get embeddings
        vectors = [np.array(item.Todo.embedding) for item in results]
        X = np.array(vectors, dtype=np.float64)
        
        # 3. K-Means Classification
        self.kmeans = KMeans(n_clusters=self.n_clusters, random_state=42)
        labels = self.kmeans.fit_predict(X)
        
        # 4. 给每个簇打标签 找离中心最近的点
        for i in range(self.n_clusters):
            # 获取该簇所有点的索引
            indices = np.where(labels == i)[0]
            if len(indices) > 0:
                # 计算该簇的中心点
                center = self.kmeans.cluster_centers_[i]
                # 在该簇中找到距离中心最近的那个向量在欧氏距离下
                cluster_vectors = X[indices]
                distances = np.linalg.norm(cluster_vectors - center, axis=1)
                min_idx = np.argmin(distances)
                # 对应的原始索引
                real_idx = indices[min_idx]
                
                self.cluster_map[i] = results[real_idx].Todo.content
        
        print(f">>> [ML] 智能分类结果: {self.cluster_map}")

        # 5. build transition matrix
        transitions = np.zeros((self.n_clusters, self.n_clusters))
        
        for i in range(len(labels) - 1):
            curr_node = results[i]
            next_node = results[i+1]
            
            # compute time difference in seconds
            time_diff = (next_node.Interaction.timestamp - curr_node.Interaction.timestamp).total_seconds()
            
            # 如果两个任务间隔超过 4 小时 (14400秒)，可能隔夜了或中断
            # No matter how, we skip this transition to reduce noise
            if time_diff > 14400:
                continue

            # only short time gap, count transition
            curr_label = labels[i]
            next_label = labels[i+1]
            transitions[curr_label][next_label] += 1
            
        # normalize to probabilities
        row_sums = transitions.sum(axis=1)
        self.transition_matrix = np.divide(
            transitions, row_sums[:, np.newaxis], 
            out=np.zeros_like(transitions), where=row_sums[:, np.newaxis]!=0
        )
        
        print(">>> [ML] 转移矩阵构建完成 (已剔除跨天噪声)")
        return "Success"

    def predict(self, current_vector):
        if self.kmeans is None:
            return "模型未训练"
            
        # 1. classify current vector
        current_cluster = self.kmeans.predict(np.array(current_vector, dtype=np.float64).reshape(1, -1))[0]
        
        # 2. search next best cluster
        probs = self.transition_matrix[current_cluster]
        
        # debug info
        print(f"DEBUG: 当前处于分类 [{self.cluster_map.get(current_cluster)}] -> 下一步概率分布: {probs}")
        
        best_next_cluster = np.argmax(probs)
        probability = probs[best_next_cluster]
        
        if probability < 0.1:
            return None
            
        suggestion = self.cluster_map.get(best_next_cluster, "未知")
        return f"猜你想做: {suggestion} (概率: {int(probability*100)}%)"
    
class MLEngine:
    def __init__(self):
        # 1. 强制使用绝对路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.model_path = os.path.join(current_dir, "todo_model.pkl")
        
        print(f"\n🔍 [ML Init] 模型文件路径设定为: {self.model_path}")
        
        self.personal_chain = defaultdict(lambda: defaultdict(int))
        self.is_trained = False
        
        #init: 尝试加载已有模型
        self.load_model()
        
    def predict(self, current_content, global_transitions=None, hot_list=None):
        """
        三级预测模型
        :param current_content: 用户当前做的任务
        :param global_transitions: 全局共现矩阵 (协同层)
        :param hot_list: 全网热榜 (探出层)
        """
        keyword = self._extract_keyword(current_content)
        
        # --- 第1层：个人习惯 (Personal Markov) ---
        candidates = self.personal_chain.get(keyword)
        if candidates:
            best_next = max(candidates, key=candidates.get)
            return f"🎯 [个人习惯] 根据你的历史，建议: {best_next}"
        
        # --- 第2层：全局协同 (Global/Collaborative) ---
        if global_transitions and keyword in global_transitions:
            suggestion = global_transitions[keyword]
            return f"👥 [大家都在做] 很多人做完这个会去: {suggestion}"
        
        # --- 第3层：探出/热度层 (Exploration/Hot) ---
        if hot_list and len(hot_list) > 0:
            top_one = hot_list[0]['content']
            return f"🔥 [全网热搜] 不知道做什么？试试这个: {top_one}"

        return "💡 [冷启动] 还没想好？去探索点新任务吧！"

    # =========================================
    # training and studing methods
    # =========================================
    def train(self, tasks_data):
        """训练模型 (构建马尔可夫链)"""
        if not tasks_data:
            return "数据为空，无法训练"

        try:
            sorted_tasks = sorted(tasks_data, key=lambda x: x['start_time'])
        except:
            sorted_tasks = tasks_data
        
        count = 0
        self.personal_chain.clear() 
        
        for i in range(len(sorted_tasks) - 1):
            curr = self._extract_keyword(sorted_tasks[i]['content'])
            next_t = self._extract_keyword(sorted_tasks[i+1]['content'])
            
            if curr and next_t:
                self.personal_chain[curr][next_t] += 1
                count += 1

        self.is_trained = True
        self.save_model()
        return f"训练成功！学习了 {count} 组行为关联。"

    # =========================================
    # 工具函数 分词与提取
    # =========================================
    def extract_tags(self, content):
        """Jieba 分词提取标签"""
        if not content:
            return []
        content = str(content)
        clean_content = content
        if "]" in content:
            clean_content = content.split("]")[-1].strip()
            
        words = jieba.lcut(clean_content)
        tags = [w for w in words if len(w) > 1] # 过滤单字
        
        if not tags and clean_content:
            return [clean_content]
        return tags

    def _extract_keyword(self, content):
        """内部使用的关键词提取"""
        tags = self.extract_tags(content)
        return tags[0] if tags else str(content).strip()

    # =========================================
    # 持久化 (Save/Load)
    # =========================================
    def save_model(self):
        """保存模型到硬盘"""
        try:
            with open(self.model_path, 'wb') as f:
                # defaultdict 不能直接 pickle，转成普通 dict
                plain_dict = {k: dict(v) for k, v in self.personal_chain.items()}
                pickle.dump(plain_dict, f)
            print(f">>> [ML] 模型保存成功: {self.model_path}")
        except Exception as e:
            print(f"❌ [ML] 保存失败: {e}")

    def load_model(self):
        """从硬盘加载模型"""
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, 'rb') as f:
                    data = pickle.load(f)
                    self.personal_chain.clear()
                    # 恢复 defaultdict 结构
                    for k, v in data.items():
                        for next_k, count in v.items():
                            self.personal_chain[k][next_k] = count
                    self.is_trained = True
                    print(">>> [ML] 历史模型加载成功")
            except Exception as e:
                print(f"⚠️ [ML] 加载失败: {e}")
                self.is_trained = False
        else:
            print(">>> [ML] 无历史模型，等待训练...")
            self.is_trained = False

# 实例化
predictor = MLEngine()
global_model = BehaviorModel()
