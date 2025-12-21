import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sqlalchemy.orm import Session
from app import models
import os
import pickle
from collections import defaultdict

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
        # 1. 强制使用绝对路径 (防止相对路径带来的混乱)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.model_path = os.path.join(current_dir, "todo_model.pkl")
        
        print(f"\n🔍 [ML Init] 模型文件路径设定为: {self.model_path}")
        
        self.markov_chain = defaultdict(lambda: defaultdict(int))
        self.is_trained = False
        
        #init: 尝试加载已有模型
        self.load_model()

    def train(self, tasks_data):
        """训练模型"""
        print(f"💪 [ML Train] 开始训练，收到 {len(tasks_data)} 条数据")
        
        if not tasks_data:
            return "数据为空，无法训练"

        try:
            sorted_tasks = sorted(tasks_data, key=lambda x: x['start_time'])
        except:
            sorted_tasks = tasks_data
        
        count = 0
        self.markov_chain.clear() 
        
        for i in range(len(sorted_tasks) - 1):
            curr = self._extract_keyword(sorted_tasks[i]['content'])
            next_t = self._extract_keyword(sorted_tasks[i+1]['content'])
            
            if curr and next_t:
                self.markov_chain[curr][next_t] += 1
                count += 1

        self.is_trained = True
        print(f"✅ [ML Train] 内存训练完成，生成了 {count} 个关联规则")
        self.save_model()
        return f"训练成功！学习了 {count} 组行为关联。"

    def predict(self, current_content):
        """预测下一步"""
        print(f"🤔 [ML Predict] 收到请求: '{current_content}'")
        print(f"    当前状态: is_trained={self.is_trained}")

        #fix point: try load if not trained
        if not self.is_trained:
            print("    状态为未训练，尝试从硬盘紧急加载...")
            self.load_model()
            print(f"    重载后状态: is_trained={self.is_trained}")
            
        if not self.is_trained:
            print("❌ [ML Predict] 最终放弃：模型确实未训练")
            return "模型未训练 (即使尝试加载文件也失败了，请检查后端日志)"
            
        keyword = self._extract_keyword(current_content)
        print(f"    提取关键词: '{keyword}'")
        
        next_candidates = self.markov_chain.get(keyword)
        
        if not next_candidates:
            #Match similar keys
            for k in self.markov_chain:
                if k in keyword or keyword in k:
                    next_candidates = self.markov_chain[k]
                    print(f"    模糊匹配成功: '{k}' -> {dict(next_candidates)}")
                    break
            
            if not next_candidates:
                print(f"    没有找到关于 '{keyword}' 的后续动作")
                return f"暂无关于'{keyword}'的习惯，去探索新事物吧！"
            
        best_next = max(next_candidates, key=next_candidates.get)
        print(f"🎯 [ML Predict] 预测结果: {best_next}")
        return f"根据习惯，你可能想去: {best_next}"

    def _extract_keyword(self, content):
        if not content: return ""
        content = str(content)
        if "]" in content:
            return content.split("]")[-1].strip()
        return content.strip()

    def save_model(self):
        """保存模型到硬盘"""
        try:
            print(f"💾 [ML Save] 正在保存到: {self.model_path}")
            with open(self.model_path, 'wb') as f:
                plain_dict = {k: dict(v) for k, v in self.markov_chain.items()}
                pickle.dump(plain_dict, f)
            print("✅ [ML Save] 保存成功！")
        except Exception as e:
            print(f"❌ [ML Save] 保存失败！！！错误: {e}")

    def load_model(self):
        """从硬盘加载模型"""
        print(f"📂 [ML Load] 正在检查文件: {self.model_path}")
        
        if os.path.exists(self.model_path):
            print("    文件存在 ✅")
            try:
                with open(self.model_path, 'rb') as f:
                    data = pickle.load(f)
                    
                    #check out data validity
                    if not data:
                        print("    ⚠️ 警告：文件里的数据是空的！")
                    else:
                        print(f"    读取到数据: 包含 {len(data)} 个主关键词")
                        
                    self.markov_chain.clear()
                    for k, v in data.items():
                        for next_k, count in v.items():
                            self.markov_chain[k][next_k] = count
                            
                    self.is_trained = True
                    print("✅ [ML Load] 加载成功，引擎已就绪")
            except Exception as e:
                print(f"❌ [ML Load] 文件读取报错: {e}")
                self.is_trained = False
        else:
            print("❌ [ML Load] 文件不存在 ❌ (需要先点击训练)")
            self.is_trained = False
            
predictor = MLEngine()          
global_model = BehaviorModel()
