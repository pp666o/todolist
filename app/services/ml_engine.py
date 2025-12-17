import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sqlalchemy.orm import Session
from app import models

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

global_model = BehaviorModel()