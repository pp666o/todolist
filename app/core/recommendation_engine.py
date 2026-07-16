import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from typing import Dict, List, Tuple, Optional, Union, Any
import torch
import torch.nn as nn
import torch.nn.functional as F
from scipy.sparse import csr_matrix
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import StandardScaler, MinMaxScaler
import networkx as nx
import random
import math
import time
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import torch.optim as optim

class RecommendationEngine:
    def __init__(self, alpha=0.5, decay_factor=0.95, diversity_weight=0.2):
        self.user_item_matrix = None
        self.user_factors = None
        self.item_factors = None
        self.user_mapping = {}  # 用户ID到矩阵索引的映射
        self.item_mapping = {}  # 物品ID到矩阵索引的映射
        self.reverse_user_mapping = {}  # 矩阵索引到用户ID的映射
        self.reverse_item_mapping = {}  # 矩阵索引到物品ID的映射
        
        # 添加新属性
        self.item_content_features = {}  # 物品内容特征
        self.user_profiles = {}  # 用户画像
        self.item_profiles = {}  # 物品画像
        self.user_item_interactions = {}  # 用户-物品交互记录
        self.item_popularity = {}  # 物品流行度
        self.user_item_timestamps = {}  # 用户-物品交互时间戳
        
        # 模型参数
        self.alpha = alpha  # 时间衰减系数
        self.decay_factor = decay_factor  # 时间衰减因子
        self.diversity_weight = diversity_weight  # 多样性权重
        
        # 相似度矩阵
        self.user_similarity_matrix = None
        self.item_similarity_matrix = None
        self.content_similarity_matrix = None
        
        # 上下文信息
        self.item_context_features = {}  # 物品上下文特征
        self.user_sequence_data = {}  # 用户序列数据
        
        # 模型组件
        self.svd_model = None
        self.deep_model = None
        
        # 初始化物品流行度分数存储
        self.item_popularity_scores = {}
        # 初始化时计算一次基础流行度 (在实际应用中可能需要定期更新)
        self._calculate_item_popularity()
    
    def build_user_item_matrix(self, ratings_data: List[Dict]) -> csr_matrix:
        """构建用户-物品评分矩阵"""
        # 提取所有唯一用户和物品
        users = set()
        items = set()
        for rating in ratings_data:
            users.add(rating['user_id'])
            items.add(rating['item_id'])
        
        # 构建映射
        self.user_mapping = {user_id: i for i, user_id in enumerate(users)}
        self.item_mapping = {item_id: i for i, item_id in enumerate(items)}
        self.reverse_user_mapping = {i: user_id for user_id, i in self.user_mapping.items()}
        self.reverse_item_mapping = {i: item_id for item_id, i in self.item_mapping.items()}
        
        # 构建评分列表
        rows = []
        cols = []
        data = []
        for rating in ratings_data:
            user_idx = self.user_mapping[rating['user_id']]
            item_idx = self.item_mapping[rating['item_id']]
            rows.append(user_idx)
            cols.append(item_idx)
            data.append(rating['rating'])
        
        # 创建稀疏矩阵
        self.user_item_matrix = csr_matrix(
            (data, (rows, cols)), 
            shape=(len(users), len(items))
        )
        
        return self.user_item_matrix
    
    def train_matrix_factorization(self, n_factors: int = 20, 
                                  n_iterations: int = 20,
                                  regularization: float = 0.1) -> Tuple:
        """训练矩阵分解模型"""
        # 使用截断SVD进行矩阵分解
        svd = TruncatedSVD(n_components=n_factors, random_state=42)
        self.item_factors = svd.fit_transform(self.user_item_matrix.T)
        self.user_factors = self.user_item_matrix.dot(self.item_factors) / np.array(
            svd.singular_values_).reshape(-1, n_factors)
        
        return self.user_factors, self.item_factors
    
    def train_deep_collaborative_filtering(self, n_factors: int = 20,
                                         n_epochs: int = 20,
                                         learning_rate: float = 0.01) -> None:
        """训练深度协同过滤模型"""
        # 创建PyTorch模型
        class MatrixFactorization(nn.Module):
            def __init__(self, n_users, n_items, n_factors):
                super().__init__()
                self.user_factors = nn.Embedding(n_users, n_factors)
                self.item_factors = nn.Embedding(n_items, n_factors)
                
                # 初始化
                self.user_factors.weight.data.uniform_(0, 0.05)
                self.item_factors.weight.data.uniform_(0, 0.05)
                
            def forward(self, user, item):
                u = self.user_factors(user)
                v = self.item_factors(item)
                return (u * v).sum(1)
        
        # 准备训练数据
        users, items, ratings = [], [], []
        for i, j in zip(*self.user_item_matrix.nonzero()):
            users.append(i)
            items.append(j)
            ratings.append(self.user_item_matrix[i, j])
        
        users = torch.LongTensor(users)
        items = torch.LongTensor(items)
        ratings = torch.FloatTensor(ratings)
        
        # 初始化模型
        model = MatrixFactorization(
            self.user_item_matrix.shape[0],
            self.user_item_matrix.shape[1],
            n_factors
        )
        
        # 损失函数和优化器
        loss_fn = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        
        # 训练
        model.train()
        for epoch in range(n_epochs):
            # 前向传播
            y_hat = model(users, items)
            loss = loss_fn(y_hat, ratings)
            
            # 反向传播
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            if (epoch + 1) % 5 == 0:
                print(f'Epoch {epoch+1}/{n_epochs}, Loss: {loss.item():.4f}')
        
        # 保存学习到的因子
        with torch.no_grad():
            self.user_factors = model.user_factors.weight.detach().numpy()
            self.item_factors = model.item_factors.weight.detach().numpy()
    
    def recommend_items(self, user_id: str, top_k: int = 10,
                      exclude_rated: bool = True) -> List[Dict]:
        """为用户推荐物品"""
        if user_id not in self.user_mapping:
            return []
        
        user_idx = self.user_mapping[user_id]
        user_vector = self.user_factors[user_idx].reshape(1, -1)
        
        # 计算与所有物品的相似度
        scores = cosine_similarity(user_vector, self.item_factors)[0]
        
        # 排除用户已评分的物品
        if exclude_rated:
            rated_items = set(self.user_item_matrix[user_idx].nonzero()[1])
            scores = np.array([
                score if i not in rated_items else -float('inf')
                for i, score in enumerate(scores)
            ])
        
        # 获取top-k物品
        top_item_indices = scores.argsort()[-top_k:][::-1]
        
        # 返回推荐结果
        recommendations = []
        for idx in top_item_indices:
            if scores[idx] > -float('inf'):
                item_id = self.reverse_item_mapping[idx]
                recommendations.append({
                    'item_id': item_id,
                    'score': float(scores[idx])
                })
        
        return recommendations
    
    def similar_items(self, item_id: str, top_k: int = 10) -> List[Dict]:
        """查找相似物品"""
        if item_id not in self.item_mapping:
            return []
        
        item_idx = self.item_mapping[item_id]
        item_vector = self.item_factors[item_idx].reshape(1, -1)
        
        # 计算与所有物品的相似度
        scores = cosine_similarity(item_vector, self.item_factors)[0]
        
        # 排除自身
        scores[item_idx] = -float('inf')
        
        # 获取top-k物品
        top_item_indices = scores.argsort()[-top_k:][::-1]
        
        # 返回相似物品
        similar_items = []
        for idx in top_item_indices:
            if scores[idx] > -float('inf'):
                similar_id = self.reverse_item_mapping[idx]
                similar_items.append({
                    'item_id': similar_id,
                    'similarity': float(scores[idx])
                })
        
        return similar_items
    
    def evaluate_recommendations(self, test_ratings: List[Dict]) -> Dict:
        """评估推荐系统性能"""
        from sklearn.metrics import mean_squared_error, mean_absolute_error
        
        # 预测评分
        actual = []
        predicted = []
        
        for rating in test_ratings:
            user_id = rating['user_id']
            item_id = rating['item_id']
            
            if user_id in self.user_mapping and item_id in self.item_mapping:
                user_idx = self.user_mapping[user_id]
                item_idx = self.item_mapping[item_id]
                
                # 预测评分
                user_vec = self.user_factors[user_idx]
                item_vec = self.item_factors[item_idx]
                pred_rating = np.dot(user_vec, item_vec)
                
                actual.append(rating['rating'])
                predicted.append(pred_rating)
        
        # 计算评估指标
        metrics = {}
        if actual:
            metrics['rmse'] = np.sqrt(mean_squared_error(actual, predicted))
            metrics['mae'] = mean_absolute_error(actual, predicted)
        
        return metrics
    
    def add_item_content_features(self, item_id: str, features: Dict) -> None:
        """添加物品内容特征"""
        self.item_content_features[item_id] = features
        # 如果物品已存在，更新特征
        if item_id in self.item_profiles:
            self.item_profiles[item_id].update({
                "content_features": features
            })
    
    def add_user_profile(self, user_id: str, profile: Dict) -> None:
        """添加用户资料"""
        self.user_profiles[user_id] = profile
        # 更新用户特征矩阵，如果已经存在
        if self.user_factors is not None and user_id in self.user_mapping:
            # 这里可以更新用户因子，但需要重新训练模型
            pass
    
    def add_item_profile(self, item_id: str, profile: Dict) -> None:
        """添加物品资料"""
        self.item_profiles[item_id] = profile
        # 更新物品特征矩阵，如果已经存在
        if self.item_factors is not None and item_id in self.item_mapping:
            # 这里可以更新物品因子，但需要重新训练模型
            pass
    
    def add_user_item_interaction(self, user_id: str, item_id: str, 
                                  rating: float, timestamp: Optional[datetime] = None) -> None:
        """添加用户-物品交互记录"""
        if timestamp is None:
            timestamp = datetime.now()
            
        # 初始化用户交互字典
        if user_id not in self.user_item_interactions:
            self.user_item_interactions[user_id] = {}
            
        # 记录交互评分
        self.user_item_interactions[user_id][item_id] = rating
        
        # 记录交互时间
        if user_id not in self.user_item_timestamps:
            self.user_item_timestamps[user_id] = {}
        self.user_item_timestamps[user_id][item_id] = timestamp
        
        # 更新物品流行度
        if item_id not in self.item_popularity:
            self.item_popularity[item_id] = 0
        self.item_popularity[item_id] += 1
        
        # 更新用户序列数据
        if user_id not in self.user_sequence_data:
            self.user_sequence_data[user_id] = []
        self.user_sequence_data[user_id].append((item_id, timestamp, rating))
        # 按时间戳排序
        self.user_sequence_data[user_id].sort(key=lambda x: x[1])
        
        # 如果已经构建了矩阵，需要更新矩阵
        if self.user_item_matrix is not None and user_id in self.user_mapping and item_id in self.item_mapping:
            user_idx = self.user_mapping[user_id]
            item_idx = self.item_mapping[item_id]
            self.user_item_matrix[user_idx, item_idx] = rating
    
    def calculate_content_similarity(self) -> np.ndarray:
        """计算物品内容相似度矩阵"""
        # 如果物品内容特征为空，返回None
        if not self.item_content_features:
            return None
            
        # 获取所有物品ID和特征
        item_ids = list(self.item_content_features.keys())
        
        # 构建特征矩阵
        feature_names = set()
        for features in self.item_content_features.values():
            feature_names.update(features.keys())
        
        feature_names = list(feature_names)
        feature_matrix = np.zeros((len(item_ids), len(feature_names)))
        
        # 填充特征矩阵
        for i, item_id in enumerate(item_ids):
            features = self.item_content_features[item_id]
            for j, feature_name in enumerate(feature_names):
                feature_matrix[i, j] = features.get(feature_name, 0)
        
        # 标准化特征
        scaler = StandardScaler()
        feature_matrix = scaler.fit_transform(feature_matrix)
        
        # 计算余弦相似度
        similarity_matrix = cosine_similarity(feature_matrix)
        
        # 保存物品ID到索引的映射
        item_to_idx = {item_id: i for i, item_id in enumerate(item_ids)}
        
        # 保存相似度矩阵和映射关系
        self.content_similarity_matrix = similarity_matrix
        
        return similarity_matrix
        
    def recommend_by_content(self, user_id: str, top_k: int = 10, 
                           min_similarity: float = 0.2) -> List[Dict]:
        """基于内容的推荐"""
        if user_id not in self.user_item_interactions:
            return []
            
        # 获取用户交互过的物品
        interacted_items = self.user_item_interactions[user_id]
        
        # 如果内容相似度矩阵尚未计算，先计算
        if self.content_similarity_matrix is None:
            self.calculate_content_similarity()
            
        # 如果仍然为空，说明没有内容特征
        if self.content_similarity_matrix is None:
            return []
            
        # 获取物品ID和索引映射
        item_ids = list(self.item_content_features.keys())
        item_to_idx = {item_id: i for i, item_id in enumerate(item_ids)}
        
        # 候选物品评分
        candidate_scores = {}
        
        # 基于用户交互物品，找到相似物品
        for item_id, rating in interacted_items.items():
            # 如果物品不在内容特征中，跳过
            if item_id not in item_to_idx:
                continue
                
            item_idx = item_to_idx[item_id]
            
            # 考虑时间衰减
            time_weight = 1.0
            if user_id in self.user_item_timestamps and item_id in self.user_item_timestamps[user_id]:
                timestamp = self.user_item_timestamps[user_id][item_id]
                days_elapsed = (datetime.now() - timestamp).days
                time_weight = self.decay_factor ** days_elapsed
            
            # 计算该物品对候选物品的贡献得分
            for candidate_id in item_ids:
                # 跳过用户已交互过的物品
                if candidate_id in interacted_items:
                    continue
                    
                # 获取相似度
                candidate_idx = item_to_idx[candidate_id]
                similarity = self.content_similarity_matrix[item_idx, candidate_idx]
                
                # 如果相似度低于阈值，跳过
                if similarity < min_similarity:
                    continue
                    
                # 计算贡献得分：相似度 * 评分 * 时间权重
                contribution = similarity * rating * time_weight
                
                # 累加贡献得分
                if candidate_id not in candidate_scores:
                    candidate_scores[candidate_id] = 0
                candidate_scores[candidate_id] += contribution
        
        # 排序并返回推荐结果
        recommendations = []
        for item_id, score in candidate_scores.items():
            recommendations.append({
                'item_id': item_id,
                'score': float(score),
                'source': 'content_based'
            })
        
        # 按得分排序
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        
        return recommendations[:top_k]
    
    def recommend_by_sequence(self, user_id: str, top_k: int = 10, 
                            max_sequence_length: int = 5) -> List[Dict]:
        """基于用户交互序列的推荐"""
        if user_id not in self.user_sequence_data or not self.user_sequence_data[user_id]:
            return []
            
        # 获取用户最近的交互序列，按时间排序
        user_sequence = self.user_sequence_data[user_id][-max_sequence_length:]
        recent_items = [item_id for item_id, _, _ in user_sequence]
        
        # 构建序列模式字典
        sequence_patterns = {}
        
        # 在所有用户中寻找相似序列模式
        for other_id, other_sequence in self.user_sequence_data.items():
            if other_id == user_id or len(other_sequence) < 2:
                continue
                
            # 将其他用户的序列转换为物品ID列表
            other_items = [item_id for item_id, _, _ in other_sequence]
            
            # 在其他用户序列中查找用户的最近交互模式
            for i in range(len(other_items) - 1):
                # 检查是否与用户最近的交互物品匹配
                if other_items[i] in recent_items:
                    next_item = other_items[i + 1]
                    
                    # 排除用户已交互过的物品
                    if next_item in self.user_item_interactions.get(user_id, {}):
                        continue
                        
                    # 记录模式频率
                    if next_item not in sequence_patterns:
                        sequence_patterns[next_item] = 0
                    sequence_patterns[next_item] += 1
        
        # 转换为推荐列表
        recommendations = []
        for item_id, frequency in sequence_patterns.items():
            # 计算序列相关性分数
            relevance_score = frequency
            
            # 如果有物品流行度，考虑流行度
            if item_id in self.item_popularity:
                # 使用流行度的对数，避免流行物品过度主导
                popularity = math.log1p(self.item_popularity[item_id])
                # 结合相关性和流行度
                score = relevance_score * (1 - self.alpha) + popularity * self.alpha
            else:
                score = relevance_score
                
            recommendations.append({
                'item_id': item_id,
                'score': float(score),
                'source': 'sequence_based'
            })
            
        # 按得分排序
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        
        return recommendations[:top_k]
        
    def recommend_by_context(self, user_id: str, context: Dict, top_k: int = 10) -> List[Dict]:
        """基于上下文的推荐"""
        if user_id not in self.user_profiles:
            return []
            
        # 获取用户资料
        user_profile = self.user_profiles[user_id]
        
        # 上下文特征
        context_time = context.get('time')
        context_location = context.get('location')
        context_device = context.get('device')
        context_activity = context.get('activity')
        
        # 候选物品分数
        candidate_scores = {}
        
        # 对每个物品计算上下文匹配分数
        for item_id, item_profile in self.item_profiles.items():
            # 跳过用户已交互的物品
            if item_id in self.user_item_interactions.get(user_id, {}):
                continue
                
            # 基础分数
            base_score = 0.0
            
            # 时间上下文匹配（如早上推荐早餐，晚上推荐夜生活）
            if context_time and 'suitable_time' in item_profile:
                if context_time in item_profile['suitable_time']:
                    base_score += 1.0
                    
            # 位置上下文匹配
            if context_location and 'suitable_location' in item_profile:
                if context_location in item_profile['suitable_location']:
                    base_score += 1.0
                    
            # 设备上下文匹配
            if context_device and 'suitable_device' in item_profile:
                if context_device in item_profile['suitable_device']:
                    base_score += 0.5
                    
            # 活动上下文匹配
            if context_activity and 'suitable_activity' in item_profile:
                if context_activity in item_profile['suitable_activity']:
                    base_score += 1.5
                    
            # 如果至少有一项上下文匹配
            if base_score > 0:
                # 添加用户偏好匹配分数
                preference_score = 0.0
                
                # 匹配用户偏好与物品特征
                if 'preferences' in user_profile and 'features' in item_profile:
                    # 计算偏好匹配程度
                    for pref, value in user_profile['preferences'].items():
                        if pref in item_profile['features']:
                            preference_score += value * item_profile['features'][pref]
                            
                # 结合上下文分数和偏好分数
                final_score = base_score * 0.6 + preference_score * 0.4
                
                # 如果有流行度信息，结合流行度
                if item_id in self.item_popularity:
                    popularity = math.log1p(self.item_popularity[item_id])
                    final_score = final_score * 0.8 + popularity * 0.2
                    
                candidate_scores[item_id] = final_score
                
        # 转换为推荐列表
        recommendations = []
        for item_id, score in candidate_scores.items():
            recommendations.append({
                'item_id': item_id,
                'score': float(score),
                'source': 'context_based'
            })
            
        # 按得分排序
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        
        return recommendations[:top_k]
    
    def _calculate_diversity(self, recommendations: List[Dict]) -> float:
        """计算推荐列表的多样性，考虑多种物品特征维度"""
        if len(recommendations) <= 1:
            return 1.0
            
        item_ids = [rec['item_id'] for rec in recommendations]
        
        # 1. 计算内容特征多样性
        content_diversity = self._calculate_content_feature_diversity(item_ids)
        
        # 2. 计算标签多样性
        tag_diversity = self._calculate_tag_diversity(item_ids)
        
        # 3. 计算物品类型多样性
        type_diversity = self._calculate_type_diversity(item_ids)
        
        # 4. 计算适用人群多样性
        demographic_diversity = self._calculate_demographic_diversity(item_ids)
        
        # 加权组合多个维度的多样性
        weights = {
            'content': 0.4,
            'tag': 0.3,
            'type': 0.2,
            'demographic': 0.1
        }
        
        weighted_diversity = (
            content_diversity * weights['content'] +
            tag_diversity * weights['tag'] +
            type_diversity * weights['type'] +
            demographic_diversity * weights['demographic']
        )
        
        return weighted_diversity
    
    def _calculate_content_feature_diversity(self, item_ids: List[str]) -> float:
        """计算物品内容特征多样性"""
        # 如果物品内容特征为空，返回默认多样性
        if not self.item_content_features:
            return 0.5
            
        # 筛选有内容特征的物品
        valid_item_ids = [item_id for item_id in item_ids if item_id in self.item_content_features]
        if len(valid_item_ids) <= 1:
            return 1.0
            
        # 计算物品间平均相似度
        total_similarity = 0.0
        count = 0
        
        for i in range(len(valid_item_ids)):
            for j in range(i + 1, len(valid_item_ids)):
                item1 = valid_item_ids[i]
                item2 = valid_item_ids[j]
                
                # 计算相似度
                similarity = self._calculate_item_content_similarity(item1, item2)
                if similarity is not None:
                    total_similarity += similarity
                    count += 1
        
        # 如果没有计算过相似度，返回默认值
        if count == 0:
            return 0.5
            
        # 平均相似度
        avg_similarity = total_similarity / count
        
        # 多样性 = 1 - 平均相似度
        return 1.0 - avg_similarity
    
    def _calculate_tag_diversity(self, item_ids: List[str]) -> float:
        """计算物品标签多样性"""
        # 收集所有物品的标签
        all_tags = []
        tag_counts = {}
        
        for item_id in item_ids:
            if item_id in self.item_profiles and 'tags' in self.item_profiles[item_id]:
                item_tags = self.item_profiles[item_id]['tags']
                if isinstance(item_tags, list):
                    all_tags.extend(item_tags)
                    # 统计每个标签出现次数
                    for tag in item_tags:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        # 如果没有标签，返回默认值
        if not all_tags:
            return 0.5
            
        # 计算标签分布的均匀程度
        total_tags = len(all_tags)
        unique_tags = len(tag_counts)
        
        # 计算标签分布的熵
        entropy = 0.0
        for count in tag_counts.values():
            probability = count / total_tags
            entropy -= probability * math.log(probability)
            
        # 标准化熵，使其范围在0-1之间
        max_entropy = math.log(unique_tags) if unique_tags > 0 else 0
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0
        
        # 另一个多样性指标：唯一标签比例
        unique_ratio = unique_tags / total_tags if total_tags > 0 else 0
        
        # 综合多样性：熵和唯一比例的加权组合
        return normalized_entropy * 0.7 + unique_ratio * 0.3
    
    def _calculate_type_diversity(self, item_ids: List[str]) -> float:
        """计算物品类型多样性"""
        # 收集所有物品的类型
        item_types = []
        
        for item_id in item_ids:
            if item_id in self.item_profiles and 'type' in self.item_profiles[item_id]:
                item_type = self.item_profiles[item_id]['type']
                item_types.append(item_type)
        
        # 如果没有类型信息，返回默认值
        if not item_types:
            return 0.5
            
        # 计算类型分布
        type_counts = {}
        for item_type in item_types:
            type_counts[item_type] = type_counts.get(item_type, 0) + 1
            
        # 计算类型分布的均匀程度
        total_items = len(item_types)
        unique_types = len(type_counts)
        
        # 类型多样性：不同类型的比例
        type_diversity = unique_types / total_items if total_items > 0 else 0
        
        # 计算类型分布的均匀程度
        distribution_uniformity = 0.0
        ideal_count = total_items / unique_types if unique_types > 0 else 0
        
        if ideal_count > 0:
            # 计算每种类型与理想均匀分布的偏差
            deviations = [abs(count - ideal_count) / ideal_count for count in type_counts.values()]
            avg_deviation = sum(deviations) / len(deviations) if deviations else 0
            distribution_uniformity = 1.0 - min(1.0, avg_deviation)
        
        # 综合多样性：类型多样性和分布均匀程度的加权组合
        return type_diversity * 0.6 + distribution_uniformity * 0.4
    
    def _calculate_demographic_diversity(self, item_ids: List[str]) -> float:
        """计算适用人群多样性"""
        # 收集所有物品的适用人群特征
        gender_targets = []
        age_ranges = []
        
        for item_id in item_ids:
            if item_id in self.item_profiles:
                profile = self.item_profiles[item_id]
                
                # 性别目标人群
                if 'target_gender' in profile:
                    gender_targets.append(profile['target_gender'])
                    
                # 年龄范围
                if 'target_age_min' in profile and 'target_age_max' in profile:
                    age_ranges.append((profile['target_age_min'], profile['target_age_max']))
        
        # 计算性别多样性
        gender_diversity = 0.5  # 默认中等多样性
        if gender_targets:
            gender_counts = {}
            for gender in gender_targets:
                gender_counts[gender] = gender_counts.get(gender, 0) + 1
                
            # 如果有多种性别目标，多样性较高
            if len(gender_counts) > 1:
                # 计算性别分布的均匀程度
                total_items = len(gender_targets)
                deviations = [abs(count - total_items/len(gender_counts)) / (total_items/len(gender_counts)) 
                            for count in gender_counts.values()]
                avg_deviation = sum(deviations) / len(deviations) if deviations else 0
                gender_diversity = 1.0 - min(1.0, avg_deviation)
        
        # 计算年龄范围多样性
        age_diversity = 0.5  # 默认中等多样性
        if age_ranges:
            # 计算年龄范围的覆盖范围
            min_age = min(range[0] for range in age_ranges)
            max_age = max(range[1] for range in age_ranges)
            total_age_span = max_age - min_age
            
            # 计算年龄范围的重叠程度
            if total_age_span > 0:
                # 创建年龄分布直方图
                age_histogram = np.zeros(int(total_age_span) + 1)
                
                for age_min, age_max in age_ranges:
                    for age in range(int(age_min - min_age), int(age_max - min_age) + 1):
                        if 0 <= age < len(age_histogram):
                            age_histogram[age] += 1
                
                # 计算年龄覆盖的均匀程度
                age_coverage = np.sum(age_histogram > 0) / len(age_histogram) if len(age_histogram) > 0 else 0
                
                # 计算年龄分布的熵
                non_zero_counts = age_histogram[age_histogram > 0]
                probabilities = non_zero_counts / np.sum(non_zero_counts)
                entropy = -np.sum(probabilities * np.log(probabilities))
                max_entropy = math.log(len(non_zero_counts)) if len(non_zero_counts) > 0 else 0
                normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0
                
                # 年龄多样性：覆盖度和均匀度的加权组合
                age_diversity = age_coverage * 0.5 + normalized_entropy * 0.5
        
        # 综合人群多样性：性别多样性和年龄多样性的加权组合
        return gender_diversity * 0.4 + age_diversity * 0.6
    
    def _diversify_recommendations(self, recommendations: List[Dict], user_id: str, context: Dict = None) -> List[Dict]:
        """多样化推荐结果"""
        # TODO: 实现推荐结果多样化的逻辑
        return recommendations
        
    def hybrid_recommend(self, user_id: str, context: Dict = None, top_k: int = 10,
                       strategy_weights: Optional[Dict[str, float]] = None,
                       adaptive_factor: Optional[float] = None, # Changed to Optional
                       scenario: Optional[str] = None) -> List[Dict]: # Added scenario parameter
        """
        组合多种推荐策略生成个性化推荐列表，支持自适应流行度调整，并实现多来源因子优先级。

        参数:
            user_id: 用户ID
            context: 推荐上下文，包含场景、时间、位置等信息
            top_k: 推荐结果数量
            strategy_weights: 自定义策略权重，如未指定则使用自适应权重
            adaptive_factor: 流行度适应因子，范围从-1.0(偏好冷门)到1.0(偏好热门)，None为自动确定
            scenario: 推荐场景 (例如 'explore', 'hot_picks')

        返回:
            推荐列表，包含物品详情、分数和推荐理由
        """

        # 1. 检查用户是否为冷启动用户
        if user_id not in self.user_profiles:
            print(f"用户 {user_id} 不存在，执行冷启动处理...")
            return self.handle_cold_start_user(user_id, top_k=top_k)

        user_profile = self.user_profiles[user_id]

        # 2. 确定 adaptive_factor (优先级: API > 用户画像 > 场景 > 历史推断 > 默认)
        final_adaptive_factor = adaptive_factor # Start with API parameter

        source_of_factor = "API parameter"

        if final_adaptive_factor is None:
            # Check User Profile for novelty_preference
            novelty_preference = user_profile.get('novelty_preference') # Assume 0 (cold) to 1 (hot)
            if novelty_preference is not None:
                try:
                    novelty_preference = float(novelty_preference)
                    if 0 <= novelty_preference <= 1:
                        # Map novelty preference [0, 1] to adaptive_factor [-1, 1]
                        # 0 (cold) -> -1, 0.5 -> 0, 1 (hot) -> 1
                        final_adaptive_factor = (novelty_preference * 2.0) - 1.0
                        source_of_factor = "User Profile (novelty_preference)"
                except (ValueError, TypeError):
                    pass
            else:
                 # Check Scenario Defaults
                 if scenario:
                     scenario_defaults = {
                         'explore': -0.6,  # Explore more niche items
                         'hot_picks': 0.7, # Focus on popular items
                         'discovery': -0.4 # Mild preference for niche
                     }
                     if scenario.lower() in scenario_defaults:
                         final_adaptive_factor = scenario_defaults[scenario.lower()]
                         source_of_factor = f"Scenario Default ({scenario})"

        # If still None, use historical inference
        if final_adaptive_factor is None:
            final_adaptive_factor = self._determine_user_popularity_preference(user_id)
            source_of_factor = "Historical Inference"
            if final_adaptive_factor == 0.0: # If historical inference is neutral, mark source as default
                source_of_factor = "Default (Neutral)"
        
        # Ensure it's not None for the final step (should be 0.0 if all else failed)
        if final_adaptive_factor is None:
             final_adaptive_factor = 0.0
             source_of_factor = "Fallback Default (Neutral)"

        print(f"为用户 {user_id} 确定流行度偏好因子: {final_adaptive_factor:.2f} (来源: {source_of_factor})")

        # 3. 如果未指定策略权重，则动态计算
        if not strategy_weights:
            strategy_weights = self._calculate_adaptive_weights(user_id)
            print(f"[Debug] 为用户 {user_id} 计算的自适应权重: {strategy_weights}") # <-- 添加日志
        else:
            print(f"[Debug] 使用外部指定的策略权重: {strategy_weights}") # <-- 添加日志

        # 确保权重总和为1.0
        total_weight = sum(strategy_weights.values())
        if total_weight != 1.0 and total_weight > 0:
            for key in strategy_weights:
                strategy_weights[key] /= total_weight

        # 4. 收集各策略的推荐结果
        collaborative_recs = self.recommend_items(user_id, top_k=top_k*2) if strategy_weights.get('collaborative', 0) > 0 else []
        content_recs = self.recommend_by_content(user_id, top_k=top_k*2) if strategy_weights.get('content', 0) > 0 else []
        sequence_recs = self.recommend_by_sequence(user_id, top_k=top_k*2) if strategy_weights.get('sequence', 0) > 0 else []
        context_recs = self.recommend_by_context(user_id, context, top_k=top_k*2) if strategy_weights.get('context', 0) > 0 and context else []

        # <-- 添加日志 -->
        print(f"[Debug] 用户 {user_id} 各策略原始推荐数量:")
        print(f"  - Collaborative: {len(collaborative_recs)}")
        print(f"  - Content: {len(content_recs)}")
        print(f"  - Sequence: {len(sequence_recs)}")
        print(f"  - Context: {len(context_recs)}")
        # <-- 结束日志 -->

        # 5. 合并结果，计算加权分数 (Ensure this logic correctly handles merging scores from different strategies)
        all_items = {}
        
        # Helper function to merge recommendations
        def merge_recs(recs, strategy_name):
            weight = strategy_weights.get(strategy_name, 0.0)
            if weight == 0: return
            for item in recs:
                 item_id = item['item_id']
                 score = item.get('score', 0.0)
                 if item_id not in all_items:
                      all_items[item_id] = {'item_id': item_id, 'score': 0.0, 'sources': [], 'weight_sum': 0.0}
                 # Use weighted average instead of simple addition
                 all_items[item_id]['score'] = (all_items[item_id]['score'] * all_items[item_id]['weight_sum'] + score * weight) / (all_items[item_id]['weight_sum'] + weight)
                 all_items[item_id]['weight_sum'] += weight
                 if strategy_name not in all_items[item_id]['sources']:
                      all_items[item_id]['sources'].append(strategy_name)

        merge_recs(collaborative_recs, 'collaborative')
        merge_recs(content_recs, 'content')
        merge_recs(sequence_recs, 'sequence')
        merge_recs(context_recs, 'context')

        # <-- 添加日志 -->
        print(f"[Debug] 用户 {user_id} 合并后物品数量 (合并前): {len(all_items)}")
        # 打印前几个合并后的分数，查看分布
        # sample_merged = {k: v['score'] for k, v in list(all_items.items())[:5]}
        # print(f"  - Sample merged scores (before pop adj): {sample_merged}")
        # <-- 结束日志 -->

        # 6. 应用自适应流行度调整
        for item_id, item in all_items.items():
            # 获取物品基础流行度
            base_popularity = self.item_popularity_scores.get(item_id, 0.0)

            # 计算流行度调整乘数
            popularity_adjustment = self._get_adaptive_popularity_adjustment(base_popularity, final_adaptive_factor) # Use the final factor

            # 应用调整
            original_score = item['score']
            item['score'] = original_score * popularity_adjustment

            # 添加调整信息到推荐源
            if final_adaptive_factor != 0 and popularity_adjustment != 1.0:
                 reason = f"pop_adj:{popularity_adjustment:.2f}(factor:{final_adaptive_factor:.2f})"
                 if reason not in item['sources']:
                      item['sources'].append(reason)
                 # Optional: More descriptive labels
                 # if popularity_adjustment > 1.0:
                 #     item['sources'].append('popularity_boosted')
                 # elif popularity_adjustment < 1.0:
                 #     item['sources'].append('popularity_reduced')


        # 7. 排序并选择top_k
        # Exclude items the user has interacted with strongly (optional)
        user_interacted_items = set(self.user_item_interactions.get(user_id, {}).keys())
        
        sorted_items = sorted(
            [item for item_id, item in all_items.items() if item_id not in user_interacted_items], # Filter out interacted
            key=lambda x: x['score'],
            reverse=True
        )[:top_k]

        # --- 添加回退逻辑 ---
        if not sorted_items:
            print(f"[Warning] 用户 {user_id} 所有策略均未产生有效推荐（或均被过滤），回退到热门推荐。")
            popular_recs = self.recommend_popular_items(top_k=top_k)
            # 对热门推荐也简单格式化一下，以便后续处理
            recommendations_to_process = []
            for pop_rec in popular_recs:
                 # 确保 pop_rec 是字典并且有必要的键
                 if isinstance(pop_rec, dict) and 'item_id' in pop_rec and 'score' in pop_rec:
                      recommendations_to_process.append(pop_rec)
                 else:
                      print(f"[Warning] Popular recommendation format incorrect: {pop_rec}")
            # 如果热门推荐也没有，则返回空列表
            if not recommendations_to_process:
                 print(f"[Warning] 用户 {user_id} 连热门推荐也无法生成。")
                 # 确保返回结构一致性
                 return {
                    'recommendations': [],
                    'adaptive_factor_used': final_adaptive_factor,
                    'factor_source': source_of_factor
                 } # 返回空列表
        else:
            recommendations_to_process = sorted_items
        # --- 结束回退逻辑 ---
        
        # 8. 多样化推荐列表 (Placeholder - implement actual logic if needed)
        # recommendations = self._diversify_recommendations(sorted_items, user_id, context)
        # recommendations = self._diversify_recommendations(filtered_sorted_items, user_id, context) # 使用过滤后的列表
        recommendations = self._diversify_recommendations(recommendations_to_process, user_id, context) # 使用回退或过滤后的列表

        # 9. 生成推荐理由并添加详情
        for rec in recommendations:
            item_id = rec['item_id']
            rec['reason'] = self._generate_recommendation_reason(user_id, item_id, rec.get('sources', []))
            # Add item details if available
            if item_id in self.item_profiles:
                 rec['details'] = self.item_profiles[item_id]


        return recommendations
    
    def _calculate_adaptive_weights(self, user_id: str) -> Dict[str, float]:
        """计算用户的自适应策略权重"""
        # 默认权重
        default_weights = {
            'collaborative': 0.35,
            'content': 0.25,
            'sequence': 0.25,
            'context': 0.15
        }
        
        # 如果用户没有足够的交互数据，返回默认权重
        if user_id not in self.user_item_interactions or len(self.user_item_interactions[user_id]) < 5:
            return default_weights
            
        # 获取用户交互数据
        interactions = self.user_item_interactions[user_id]
        
        # 分析用户交互历史以确定最有效的推荐策略
        strategy_effectiveness = {
            'collaborative': 0.0,
            'content': 0.0,
            'sequence': 0.0,
            'context': 0.0
        }
        
        # 1. 评估协同过滤策略的有效性
        # 检查用户与其他用户的相似度
        if self.user_similarity_matrix is not None:
            user_idx = self.user_mapping.get(user_id)
            if user_idx is not None:
                # 计算用户与其他用户的平均相似度
                user_similarities = np.mean(self.user_similarity_matrix[user_idx])
                # 相似度越高，协同过滤越有效
                strategy_effectiveness['collaborative'] = min(1.0, user_similarities * 2)
        
        # 2. 评估基于内容的策略有效性
        # 检查用户交互物品的内容相似度
        if self.item_content_features:
            content_similarities = []
            interacted_items = list(interactions.keys())
            
            for i in range(len(interacted_items)):
                item1 = interacted_items[i]
                if item1 not in self.item_content_features:
                    continue
                    
                for j in range(i + 1, len(interacted_items)):
                    item2 = interacted_items[j]
                    if item2 not in self.item_content_features:
                        continue
                        
                    # 计算两个物品之间的内容相似度
                    similarity = self._calculate_item_content_similarity(item1, item2)
                    if similarity is not None:
                        content_similarities.append(similarity)
            
            if content_similarities:
                # 相似度的集中程度越高，基于内容的推荐越有效
                content_similarity_std = np.std(content_similarities)
                strategy_effectiveness['content'] = 1.0 - min(1.0, content_similarity_std)
        
        # 3. 评估基于序列的策略有效性
        # 检查用户交互的时间模式
        if user_id in self.user_sequence_data and len(self.user_sequence_data[user_id]) >= 3:
            # 计算交互时间间隔的规律性
            intervals = []
            sequences = self.user_sequence_data[user_id]
            for i in range(1, len(sequences)):
                interval = (sequences[i][1] - sequences[i-1][1]).total_seconds()
                intervals.append(interval)
                
            if intervals:
                # 时间间隔的规律性越高，序列推荐越有效
                interval_std = np.std(intervals)
                interval_mean = np.mean(intervals)
                if interval_mean > 0:
                    cv = interval_std / interval_mean  # 变异系数
                    strategy_effectiveness['sequence'] = 1.0 - min(1.0, cv)
        
        # 4. 评估基于上下文的策略有效性
        # 检查用户在不同上下文中的偏好差异
        context_preference_diff = 0.0
        # ... 这里可以根据实际上下文数据进行计算
        # 暂时使用一个固定值
        strategy_effectiveness['context'] = 0.5
        
        # 如果某些策略没有足够数据评估，使用默认值
        for strategy, effectiveness in strategy_effectiveness.items():
            if effectiveness == 0.0:
                strategy_effectiveness[strategy] = default_weights[strategy]
        
        # 归一化权重
        total_effectiveness = sum(strategy_effectiveness.values())
        if total_effectiveness > 0:
            adaptive_weights = {k: v / total_effectiveness for k, v in strategy_effectiveness.items()}
        else:
            adaptive_weights = default_weights
            
        return adaptive_weights
    
    def _calculate_item_content_similarity(self, item_id1: str, item_id2: str) -> Optional[float]:
        """计算两个物品之间的内容相似度"""
        if item_id1 not in self.item_content_features or item_id2 not in self.item_content_features:
            return None
            
        features1 = self.item_content_features[item_id1]
        features2 = self.item_content_features[item_id2]
        
        # 获取共同特征
        common_features = set(features1.keys()) & set(features2.keys())
        if not common_features:
            return 0.0
            
        # 计算余弦相似度
        dot_product = sum(features1[f] * features2[f] for f in common_features)
        magnitude1 = math.sqrt(sum(features1[f] ** 2 for f in features1))
        magnitude2 = math.sqrt(sum(features2[f] ** 2 for f in features2))
        
        if magnitude1 * magnitude2 == 0:
            return 0.0
            
        return dot_product / (magnitude1 * magnitude2)
    
    def _generate_recommendation_reason(self, user_id: str, item_id: str, sources: List[str]) -> str:
        """生成推荐理由"""
        if not sources:
            return "根据您的个人喜好推荐"
            
        # 物品名称
        item_name = self.item_profiles.get(item_id, {}).get('name', '此物品')
        
        # 生成基于来源的理由
        reasons = []
        
        if 'collaborative' in sources:
            reasons.append("与您喜欢的其他物品相似")
            
        if 'content' in sources:
            # 获取用户喜欢的特征
            liked_features = set()
            if user_id in self.user_item_interactions:
                for liked_item, rating in self.user_item_interactions[user_id].items():
                    if rating > 3 and liked_item in self.item_content_features:
                        for feature, value in self.item_content_features[liked_item].items():
                            if value > 0.7:
                                liked_features.add(feature)
            
            # 与物品特征匹配
            matching_features = []
            if item_id in self.item_content_features:
                for feature, value in self.item_content_features[item_id].items():
                    if value > 0.7 and feature in liked_features:
                        matching_features.append(feature)
            
            if matching_features:
                # 随机选择1-2个特征
                selected_features = random.sample(
                    matching_features, 
                    min(2, len(matching_features))
                )
                reasons.append(f"包含您喜欢的{'/'.join(selected_features)}特征")
            else:
                reasons.append("与您的品味相符")
                
        if 'sequence' in sources:
            reasons.append("基于您的浏览历史")
            
        if 'context' in sources:
            reasons.append("适合您当前的场景")
            
        # 构建完整推荐理由
        if len(reasons) == 1:
            return f"为您推荐{item_name}，{reasons[0]}"
        else:
            # 随机选择两个理由
            selected_reasons = random.sample(reasons, min(2, len(reasons)))
            return f"为您推荐{item_name}，{selected_reasons[0]}，并且{selected_reasons[1]}"
        
    def handle_cold_start_user(self, user_id: str, user_profile: Dict = None, 
                              top_k: int = 10) -> List[Dict]:
        """处理冷启动用户的推荐，增强基于人口统计学特征的初始推荐"""
        # 如果有用户画像，基于画像推荐
        if user_profile:
            self.add_user_profile(user_id, user_profile)
        elif user_id in self.user_profiles:
            user_profile = self.user_profiles[user_id]
        else:
            # 没有用户信息，返回热门物品
            return self.recommend_popular_items(top_k)
            
        # 基于用户画像特征进行内容匹配
        recommendations = []
        
        # 提取用户基本特征
        age = user_profile.get('age', 0)
        gender = user_profile.get('gender', 'unknown')
        interests = user_profile.get('interests', [])
        preferences = user_profile.get('preferences', {})
        
        # 新增人口统计学特征
        location = user_profile.get('location', '')
        education = user_profile.get('education', '')
        occupation = user_profile.get('occupation', '')
        income_level = user_profile.get('income_level', '')
        relationship_status = user_profile.get('relationship_status', '')
        lifestyle = user_profile.get('lifestyle', [])
        
        # 创建人口统计学特征分组
        # 年龄分组
        age_group = ''
        if age > 0:
            if age < 18:
                age_group = 'teen'
            elif age < 25:
                age_group = 'young_adult'
            elif age < 35:
                age_group = 'adult'
            elif age < 50:
                age_group = 'middle_age'
            else:
                age_group = 'senior'
        
        # 收入水平标准化
        normalized_income = ''
        if income_level:
            if isinstance(income_level, str):
                normalized_income = income_level.lower()
            elif isinstance(income_level, (int, float)):
                if income_level < 50000:
                    normalized_income = 'low'
                elif income_level < 100000:
                    normalized_income = 'medium'
                else:
                    normalized_income = 'high'
        
        # 对每个物品评分
        for item_id, item_profile in self.item_profiles.items():
            score = 0.0
            match_reasons = []
            
            # 1. 性别匹配
            if 'target_gender' in item_profile:
                if item_profile['target_gender'] == 'both' or item_profile['target_gender'] == gender:
                    score += 1.0
                    match_reasons.append('性别匹配')
                    
            # 2. 年龄段匹配
            if 'target_age_min' in item_profile and 'target_age_max' in item_profile:
                age_min = item_profile['target_age_min']
                age_max = item_profile['target_age_max']
                if age_min <= age <= age_max:
                    score += 1.0
                    match_reasons.append('年龄匹配')
                
                # 更精细的年龄段匹配
                if 'target_age_group' in item_profile and age_group:
                    if item_profile['target_age_group'] == age_group:
                        score += 0.5
                        match_reasons.append('年龄段精确匹配')
                    
            # 3. 兴趣标签匹配
            if 'tags' in item_profile and interests:
                matching_tags = set(interests) & set(item_profile['tags'])
                if matching_tags:
                    tag_score = len(matching_tags) * 0.5
                    score += tag_score
                    if tag_score > 0.5:
                        match_reasons.append('兴趣匹配')
                    
            # 4. 偏好特征匹配
            if 'features' in item_profile and preferences:
                preference_score = 0
                for pref, value in preferences.items():
                    if pref in item_profile['features']:
                        preference_score += value * item_profile['features'][pref] * 0.3
                score += preference_score
                if preference_score > 0.3:
                    match_reasons.append('偏好匹配')
            
            # 5. 地理位置匹配
            if location and 'target_location' in item_profile:
                target_locations = item_profile['target_location']
                if isinstance(target_locations, list):
                    if location in target_locations:
                        score += 0.8
                        match_reasons.append('位置匹配')
                elif isinstance(target_locations, str):
                    if location == target_locations:
                        score += 0.8
                        match_reasons.append('位置匹配')
            
            # 6. 教育水平匹配
            if education and 'target_education' in item_profile:
                if item_profile['target_education'] == education:
                    score += 0.6
                    match_reasons.append('教育背景匹配')
            
            # 7. 职业匹配
            if occupation and 'target_occupation' in item_profile:
                target_occupations = item_profile['target_occupation']
                if isinstance(target_occupations, list):
                    if occupation in target_occupations:
                        score += 0.7
                        match_reasons.append('职业匹配')
                elif isinstance(target_occupations, str):
                    if occupation == target_occupations:
                        score += 0.7
                        match_reasons.append('职业匹配')
            
            # 8. 收入水平匹配
            if normalized_income and 'target_income' in item_profile:
                if item_profile['target_income'] == normalized_income:
                    score += 0.5
                    match_reasons.append('收入水平匹配')
            
            # 9. 关系状态匹配
            if relationship_status and 'target_relationship_status' in item_profile:
                if item_profile['target_relationship_status'] == relationship_status:
                    score += 0.6
                    match_reasons.append('关系状态匹配')
            
            # 10. 生活方式匹配
            if lifestyle and 'target_lifestyle' in item_profile:
                target_lifestyle = item_profile['target_lifestyle']
                if isinstance(target_lifestyle, list) and isinstance(lifestyle, list):
                    matching_lifestyle = set(lifestyle) & set(target_lifestyle)
                    lifestyle_score = len(matching_lifestyle) * 0.3
                    score += lifestyle_score
                    if lifestyle_score > 0.3:
                        match_reasons.append('生活方式匹配')
            
            # 11. 社会群体匹配
            if 'social_group' in user_profile and 'target_social_group' in item_profile:
                if user_profile['social_group'] == item_profile['target_social_group']:
                    score += 0.5
                    match_reasons.append('社会群体匹配')
                
            # 12. 考虑物品流行度（热度）
            if item_id in self.item_popularity:
                popularity = math.log1p(self.item_popularity[item_id])
                pop_weight = 0.2
                # 如果用户特征非常少，增加流行度权重
                if len(match_reasons) <= 1:
                    pop_weight = 0.5
                score += popularity * pop_weight
                if popularity > 1.0:
                    match_reasons.append('热门推荐')
                
            # 如果得分大于0，添加到推荐结果
            if score > 0:
                recommendations.append({
                    'item_id': item_id,
                    'score': float(score),
                    'source': 'cold_start',
                    'match_reasons': match_reasons
                })
                
        # 按得分排序
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        
        # 为了增加多样性，应用简单的再排序
        if len(recommendations) > top_k * 2:
            final_recommendations = self._diversify_cold_start_recommendations(
                recommendations[:top_k * 2], top_k
            )
        else:
            final_recommendations = recommendations[:top_k]
        
        # 为每个推荐添加详细信息
        for rec in final_recommendations:
            item_id = rec['item_id']
            if item_id in self.item_profiles:
                rec['details'] = self.item_profiles[item_id]
                
                # 添加推荐理由
                match_reasons = rec.get('match_reasons', [])
                if match_reasons:
                    # 选择最重要的1-2个原因
                    selected_reasons = match_reasons[:min(2, len(match_reasons))]
                    rec['reason'] = f"推荐理由: {' 和 '.join(selected_reasons)}"
                else:
                    tags = self.item_profiles[item_id].get('tags', [])
                    if interests and tags:
                        matching_tags = set(interests) & set(tags)
                        if matching_tags:
                            selected_tags = list(matching_tags)[:2]
                            rec['reason'] = f"与您的{'/'.join(selected_tags)}兴趣相关"
                        else:
                            rec['reason'] = "基于您的个人资料推荐"
                    else:
                        rec['reason'] = "可能适合您的品味"
                    
        return final_recommendations
    
    def _diversify_cold_start_recommendations(self, recommendations: List[Dict], top_k: int) -> List[Dict]:
        """为冷启动用户增加推荐多样性"""
        if len(recommendations) <= top_k:
            return recommendations
            
        # 提取所有匹配原因
        all_reasons = set()
        for rec in recommendations:
            all_reasons.update(rec.get('match_reasons', []))
            
        final_recommendations = []
        
        # 按不同的匹配原因选择物品
        for reason in all_reasons:
            # 找出该原因的所有物品
            reason_items = [rec for rec in recommendations if reason in rec.get('match_reasons', [])]
            # 按得分排序
            reason_items.sort(key=lambda x: x['score'], reverse=True)
            # 选择得分最高的几个
            reason_count = max(1, int(top_k * 0.3))  # 每个原因最多占总数的30%
            selected_items = reason_items[:reason_count]
            
            # 添加到最终列表，避免重复
            for item in selected_items:
                if item not in final_recommendations and len(final_recommendations) < top_k:
                    final_recommendations.append(item)
        
        # 如果还不够，从剩余推荐中按得分添加
        remaining = [rec for rec in recommendations if rec not in final_recommendations]
        remaining.sort(key=lambda x: x['score'], reverse=True)
        
        while len(final_recommendations) < top_k and remaining:
            final_recommendations.append(remaining.pop(0))
            
        return final_recommendations
        
    def recommend_popular_items(self, top_k: int = 10, 
                              time_window_days: int = 30) -> List[Dict]:
        """推荐热门物品"""
        # 按流行度（交互次数）排序
        if not self.item_popularity:
            return []
            
        # 考虑时间窗口
        current_time = datetime.now()
        filtered_interactions = {}
        
        # 只统计时间窗口内的交互
        for user_id, timestamps in self.user_item_timestamps.items():
            for item_id, timestamp in timestamps.items():
                days_elapsed = (current_time - timestamp).days
                if days_elapsed <= time_window_days:
                    filtered_interactions.setdefault(item_id, 0)
                    filtered_interactions[item_id] += 1
        
        # 如果没有时间窗口内的交互，使用全部流行度
        if not filtered_interactions:
            filtered_interactions = self.item_popularity
            
        # 按流行度排序
        popular_items = sorted(
            filtered_interactions.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        # 构建推荐结果
        recommendations = []
        for item_id, count in popular_items[:top_k]:
            if item_id in self.item_profiles:
                recommendations.append({
                    'item_id': item_id,
                    'score': float(math.log1p(count)),
                    'popularity': count,
                    'source': 'popular',
                    'details': self.item_profiles[item_id],
                    'reason': "热门推荐，很多用户都喜欢"
                })
            else:
                recommendations.append({
                    'item_id': item_id,
                    'score': float(math.log1p(count)),
                    'popularity': count,
                    'source': 'popular',
                    'reason': "热门推荐，很多用户都喜欢"
                })
                
        return recommendations
                
    def ab_test_recommend(self, user_id: str, experiment_id: str, 
                        context: Dict = None, top_k: int = 10) -> List[Dict]:
        """支持AB测试的推荐方法"""
        # 根据用户ID和实验ID确定实验组
        user_hash = hash(user_id + experiment_id) % 100
        
        # 实验组配置
        if experiment_id == "weight_exp_1":
            if user_hash < 33:  # A组：强调协同过滤
                strategy_weights = {
                    'collaborative': 0.6,
                    'content': 0.2,
                    'sequence': 0.1,
                    'context': 0.1
                }
            elif user_hash < 66:  # B组：强调内容
                strategy_weights = {
                    'collaborative': 0.2,
                    'content': 0.6,
                    'sequence': 0.1,
                    'context': 0.1
                }
            else:  # C组：均衡
                strategy_weights = {
                    'collaborative': 0.3,
                    'content': 0.3,
                    'sequence': 0.2,
                    'context': 0.2
                }
        elif experiment_id == "diversity_exp_1":
            if user_hash < 50:  # A组：低多样性
                old_diversity = self.diversity_weight
                self.diversity_weight = 0.1
                recommendations = self.hybrid_recommend(user_id, context, top_k)
                self.diversity_weight = old_diversity
                return recommendations
            else:  # B组：高多样性
                old_diversity = self.diversity_weight
                self.diversity_weight = 0.4
                recommendations = self.hybrid_recommend(user_id, context, top_k)
                self.diversity_weight = old_diversity
                return recommendations
        else:
            # 默认配置
            strategy_weights = None
            
        # 调用混合推荐
        return self.hybrid_recommend(
            user_id=user_id, 
            context=context, 
            top_k=top_k, 
            strategy_weights=strategy_weights
        )
        
    def evaluate_comprehensive(self, test_data: List[Dict]) -> Dict:
        """综合评估推荐系统性能"""
        from sklearn.metrics import mean_squared_error, mean_absolute_error, ndcg_score, precision_score
        
        # 划分数据
        users_test = {}
        for item in test_data:
            user_id = item['user_id']
            item_id = item['item_id']
            rating = item['rating']
            timestamp = item.get('timestamp', datetime.now())
            
            if user_id not in users_test:
                users_test[user_id] = []
                
            users_test[user_id].append({
                'item_id': item_id,
                'rating': rating,
                'timestamp': timestamp
            })
            
        # 评估指标
        metrics = {
            'rmse': 0.0,
            'mae': 0.0,
            'precision': 0.0,
            'recall': 0.0,
            'ndcg': 0.0,
            'diversity': 0.0,
            'coverage': 0.0
        }
        
        # 所有预测的评分
        all_predictions = []
        all_ground_truth = []
        
        # 推荐物品集合（用于计算覆盖率）
        recommended_items = set()
        
        # 每个用户的指标
        user_metrics = {}
        
        # 总物品数（用于计算覆盖率）
        total_items = len(self.item_profiles) if self.item_profiles else len(self.item_mapping)
        
        # 对每个用户评估
        for user_id, items in users_test.items():
            if user_id not in self.user_mapping:
                continue
                
            # 排序测试项目，获取最近的k个作为测试集，其余作为训练集
            items.sort(key=lambda x: x['timestamp'])
            train_items = items[:-5]
            test_items = items[-5:]
            
            # 如果测试集为空，跳过
            if not test_items:
                continue
                
            # 获取推荐
            recommendations = self.hybrid_recommend(user_id, top_k=10)
            recommended_item_ids = [rec['item_id'] for rec in recommendations]
            
            # 更新推荐物品集合（用于计算覆盖率）
            recommended_items.update(recommended_item_ids)
            
            # 计算精确率（推荐中有多少是用户实际喜欢的）
            actual_liked = [item['item_id'] for item in test_items if item['rating'] >= 4]
            if actual_liked:
                precision = len(set(recommended_item_ids) & set(actual_liked)) / len(recommended_item_ids)
            else:
                precision = 0.0
                
            # 计算召回率（用户喜欢的物品有多少被推荐）
            if actual_liked:
                recall = len(set(recommended_item_ids) & set(actual_liked)) / len(actual_liked)
            else:
                recall = 0.0
                
            # 计算NDCG（推荐排序质量）
            if actual_liked:
                # 构建相关性列表
                relevance = []
                for item_id in recommended_item_ids:
                    # 如果在实际喜欢的物品中，相关性为1，否则为0
                    relevance.append(1 if item_id in actual_liked else 0)
                    
                # 理想的相关性列表（前len(actual_liked)个为1，其余为0）
                ideal = [1] * min(len(actual_liked), len(relevance)) + [0] * max(0, len(relevance) - len(actual_liked))
                
                # 计算DCG和IDCG
                dcg = self._dcg_at_k(relevance, len(relevance))
                idcg = self._dcg_at_k(ideal, len(relevance))
                
                ndcg = dcg / idcg if idcg > 0 else 0.0
            else:
                ndcg = 0.0
                
            # 计算多样性
            diversity = self._calculate_diversity(recommendations)
            
            # 对每个测试物品预测评分
            predictions = []
            ground_truth = []
            
            for item in test_items:
                item_id = item['item_id']
                actual_rating = item['rating']
                
                if item_id in self.item_mapping:
                    # 使用模型预测评分
                    user_idx = self.user_mapping[user_id]
                    item_idx = self.item_mapping[item_id]
                    
                    # 预测评分
                    if self.user_factors is not None and self.item_factors is not None:
                        user_vec = self.user_factors[user_idx]
                        item_vec = self.item_factors[item_idx]
                        pred_rating = np.dot(user_vec, item_vec)
                    else:
                        # 没有训练模型，使用均值
                        pred_rating = 3.0
                    
                    predictions.append(pred_rating)
                    ground_truth.append(actual_rating)
                    
                    # 添加到全局列表
                    all_predictions.append(pred_rating)
                    all_ground_truth.append(actual_rating)
            
            # 计算用户的误差指标
            if predictions:
                user_rmse = np.sqrt(mean_squared_error(ground_truth, predictions))
                user_mae = mean_absolute_error(ground_truth, predictions)
            else:
                user_rmse = 0.0
                user_mae = 0.0
                
            # 保存用户指标
            user_metrics[user_id] = {
                'rmse': user_rmse,
                'mae': user_mae,
                'precision': precision,
                'recall': recall,
                'ndcg': ndcg,
                'diversity': diversity
            }
            
            # 累加到全局指标
            metrics['precision'] += precision
            metrics['recall'] += recall
            metrics['ndcg'] += ndcg
            metrics['diversity'] += diversity
            
        # 计算平均指标
        num_users = len(user_metrics)
        if num_users > 0:
            metrics['precision'] /= num_users
            metrics['recall'] /= num_users
            metrics['ndcg'] /= num_users
            metrics['diversity'] /= num_users
            
        # 计算全局RMSE和MAE
        if all_predictions:
            metrics['rmse'] = np.sqrt(mean_squared_error(all_ground_truth, all_predictions))
            metrics['mae'] = mean_absolute_error(all_ground_truth, all_predictions)
            
        # 计算覆盖率
        if total_items > 0:
            metrics['coverage'] = len(recommended_items) / total_items
            
        return {
            'global_metrics': metrics,
            'user_metrics': user_metrics
        }
        
    def _dcg_at_k(self, relevance, k):
        """
        计算DCG@k分数
        """
        relevance = np.asfarray(relevance)[:k]
        if relevance.size:
            return np.sum(relevance / np.log2(np.arange(2, relevance.size + 2)))
        return 0.0
        
    def apply_dynamic_user_recommendations(self, user_id: str, recommendations: List[Dict], 
                          potential_users: List[Dict], context: Dict = None,
                          max_users: int = 3, min_distance: int = 2) -> List[Dict]:
        """
        实现动态用户推荐策略，在推荐列表中智能插入潜在好友/交友对象
        
        参数:
        - user_id: 用户ID
        - recommendations: 原始推荐列表(物品推荐)
        - potential_users: 可推荐的潜在好友/交友对象列表
        - context: 上下文信息，如时间、位置等
        - max_users: 最大推荐用户数量
        - min_distance: 用户推荐之间的最小距离
        
        返回:
        - 插入用户推荐后的推荐列表
        """
        if not potential_users or len(recommendations) < min_distance:
            return recommendations
            
        # 1. 确定用户对社交推荐的接受度
        social_tolerance = self._calculate_social_tolerance(user_id, context)
        
        # 2. 基于接受度调整最大推荐用户数量
        adjusted_max_users = min(max_users, int(len(recommendations) * social_tolerance * 0.3))
        if adjusted_max_users == 0:
            adjusted_max_users = 1  # 至少推荐一个用户
            
        # 3. 对潜在好友进行评分排序
        scored_users = self._score_potential_matches(user_id, potential_users, context)
        
        # 取得分最高的几个用户
        top_users = scored_users[:adjusted_max_users]
        if not top_users:
            return recommendations
            
        # 4. 确定用户推荐插入位置
        user_positions = self._determine_recommendation_positions(len(recommendations), adjusted_max_users, min_distance)
        
        # 5. 插入用户推荐
        result = recommendations.copy()
        for i, position in enumerate(user_positions):
            if i < len(top_users):
                user_rec = top_users[i].copy()
                user_rec['is_user_recommendation'] = True
                user_rec['recommendation_position'] = position
                result.insert(position, user_rec)
                
        return result
    
    def _calculate_social_tolerance(self, user_id: str, context: Dict = None) -> float:
        """计算用户对社交推荐的接受度 (0-1之间)"""
        # 默认中等接受度
        default_tolerance = 0.5
        
        # 如果用户资料不存在，返回默认值
        if user_id not in self.user_profiles:
            return default_tolerance
            
        user_profile = self.user_profiles[user_id]
        
        # 1. 检查用户明确设置的社交偏好
        if 'social_preference' in user_profile:
            social_pref = user_profile['social_preference']
            if isinstance(social_pref, (int, float)) and 0 <= social_pref <= 1:
                return social_pref
                
        # 2. 基于用户交互历史推断
        tolerance_factors = []
        
        # 2.1 社交活跃度：活跃度高的用户社交接受度较高
        if 'social_activity_level' in user_profile:
            activity_level = user_profile['social_activity_level']
            if isinstance(activity_level, (int, float)) and 0 <= activity_level <= 1:
                tolerance_factors.append(activity_level)
            else:
                tolerance_factors.append(0.5)  # 默认中等活跃度
                
        # 2.2 历史社交互动：接受好友请求率高表示接受度高
        social_acceptance_rate = 0.5  # 默认值
        if 'social_interactions' in user_profile:
            interactions = user_profile['social_interactions']
            if 'received_requests' in interactions and interactions['received_requests'] > 0:
                accepted = interactions.get('accepted_requests', 0)
                social_acceptance_rate = min(1.0, accepted / interactions['received_requests'])
            tolerance_factors.append(social_acceptance_rate)
            
        # 2.3 用户整体活跃度：活跃用户可能对社交推荐容忍度更高
        activity_level = 0.5  # 默认中等活跃度
        # 检查user_sequence_data是否存在
        if hasattr(self, 'user_sequence_data') and user_id in self.user_sequence_data:
            # 计算最近30天的活动次数
            recent_activities = [
                act for act in self.user_sequence_data[user_id]
                if (datetime.now() - act[1]).days <= 30
            ]
            if recent_activities:
                # 根据活动次数计算活跃度
                activity_count = len(recent_activities)
                activity_level = min(1.0, activity_count / 30)
            tolerance_factors.append(activity_level)
            
        # 2.4 上下文因素
        if context:
            # 时间敏感度：特定时间段可能对社交推荐容忍度不同
            hour_of_day = context.get('hour_of_day', -1)
            if 0 <= hour_of_day < 24:
                # 晚间时段(18-23点)社交接受度较高
                if 18 <= hour_of_day <= 23:
                    tolerance_factors.append(0.7)
                # 工作时段(9-17点)较低
                elif 9 <= hour_of_day <= 17:
                    tolerance_factors.append(0.4)
                # 早晨时段(6-9点)适中
                elif 6 <= hour_of_day < 9:
                    tolerance_factors.append(0.5)
                else:
                    tolerance_factors.append(0.5)
            
            # 位置因素：社交场合接受度更高
            location_type = context.get('location_type', '')
            if location_type in ['restaurant', 'cafe', 'bar', 'entertainment']:
                tolerance_factors.append(0.8)  # 社交场所
            elif location_type in ['work', 'school', 'library']:
                tolerance_factors.append(0.3)  # 工作/学习场所
            
        # 综合所有因素计算最终接受度
        if tolerance_factors:
            return sum(tolerance_factors) / len(tolerance_factors)
        else:
            return default_tolerance
    
    def _score_potential_matches(self, user_id: str, potential_users: List[Dict], context: Dict = None) -> List[Dict]:
        """对潜在匹配的用户进行个性化评分"""
        user_profile = self.user_profiles.get(user_id, {})
        scored_users = []
        
        for potential_user in potential_users:
            score = 0.0
            
            # 1. 基础分：匹配度
            base_score = potential_user.get('match_score', 0.5)
            score += base_score
            
            # 2. 相关性分：兴趣匹配度
            relevance_score = 0.0
            
            # 2.1 兴趣标签匹配
            user_interests = user_profile.get('interests', [])
            potential_user_interests = potential_user.get('interests', [])
            
            if user_interests and potential_user_interests:
                matching_interests = set(user_interests) & set(potential_user_interests)
                relevance_score += len(matching_interests) * 0.2
                
            # 2.2 人口统计学特征匹配
            if 'gender_preference' in user_profile and 'gender' in potential_user:
                if user_profile['gender_preference'] == 'all' or user_profile['gender_preference'] == potential_user['gender']:
                    relevance_score += 0.1
                    
            if 'age_preference_min' in user_profile and 'age_preference_max' in user_profile and 'age' in potential_user:
                potential_user_age = potential_user['age']
                if user_profile['age_preference_min'] <= potential_user_age <= user_profile['age_preference_max']:
                    relevance_score += 0.1
                    
            # 2.3 位置匹配
            if context and 'location' in context and 'location' in potential_user:
                user_location = context['location']
                if user_location == potential_user['location']:
                    relevance_score += 0.2
                    
            # 归一化相关性分数
            relevance_score = min(1.0, relevance_score)
            score += relevance_score * 2  # 相关性权重较高
            
            # 3. 社交因素
            social_score = 0.0
            
            # 3.1 共同好友数量
            if 'common_friends' in potential_user:
                common_friends_count = potential_user['common_friends']
                # 归一化，假设20个共同好友为满分
                social_score += min(1.0, common_friends_count / 20) * 0.5
                
            # 3.2 社交活跃度
            if 'social_activity_level' in potential_user:
                activity_level = potential_user['social_activity_level']
                if isinstance(activity_level, (int, float)) and 0 <= activity_level <= 1:
                    social_score += activity_level * 0.3
                    
            # 3.3 响应率
            if 'response_rate' in potential_user:
                response_rate = potential_user['response_rate']
                if isinstance(response_rate, (int, float)) and 0 <= response_rate <= 1:
                    social_score += response_rate * 0.2
                    
            score += social_score
            
            # 4. 上下文相关性
            context_score = 0.0
            
            if context:
                # 4.1 当前活动匹配
                if 'activity' in context and 'preferred_activities' in potential_user:
                    current_activity = context['activity']
                    if current_activity in potential_user['preferred_activities']:
                        context_score += 0.5
                        
                # 4.2 时间匹配
                if 'time_of_day' in context and 'active_times' in potential_user:
                    current_time = context['time_of_day']
                    if current_time in potential_user['active_times']:
                        context_score += 0.3
                        
            score += context_score
            
            # 保存评分结果
            scored_user = potential_user.copy()
            scored_user['score'] = score
            scored_users.append(scored_user)
            
        # 按得分排序
        scored_users.sort(key=lambda x: x['score'], reverse=True)
        return scored_users
    
    def _determine_recommendation_positions(self, list_length: int, num_users: int, min_distance: int) -> List[int]:
        """确定用户推荐在推荐列表中的最佳位置"""
        if list_length <= 0 or num_users <= 0:
            return []
            
        # 特殊情况处理
        if list_length < min_distance + 1:
            return [0]  # 只在开头放一个推荐
            
        if num_users == 1:
            # 单个用户推荐放在黄金位置：第3个位置或列表中间
            ideal_position = min(2, list_length - 1)
            return [ideal_position]
            
        # 计算可用的位置数
        available_positions = list_length + (num_users - 1) * min_distance
        
        # 计算理想间距
        ideal_spacing = available_positions / (num_users + 1)
        
        # 生成推荐位置
        positions = []
        for i in range(1, num_users + 1):
            # 计算理论上的理想位置
            ideal_pos = int(i * ideal_spacing) - 1
            
            # 调整位置，考虑前面已插入的推荐
            adjusted_pos = ideal_pos - len([p for p in positions if p < ideal_pos])
            
            # 确保不超出列表范围
            final_pos = min(adjusted_pos, list_length - 1)
            
            # 避免与已有位置太近
            while positions and min([abs(final_pos - p) for p in positions]) < min_distance:
                final_pos += 1
                if final_pos >= list_length:
                    final_pos = 0  # 重置到列表开头
                    break
                    
            positions.append(final_pos)
            
        # 确保位置有序且无重复
        positions = sorted(list(set(positions)))
        return positions[:num_users]
    
    def _process_ratings_to_interactions(self, ratings_data):
        """将评分数据转换为交互字典 (如果需要)"""
        # 这个方法的实现取决于你的 ratings_data 格式
        # 假设 ratings_data 是类似 [(user_id, item_id, rating, timestamp), ...] 的列表
        interactions = {}
        if ratings_data:
            for user_id, item_id, rating, timestamp in ratings_data:
                if user_id not in interactions:
                    interactions[user_id] = {}
                if item_id not in interactions[user_id]:
                    interactions[user_id][item_id] = []
                interactions[user_id][item_id].append({
                    # 根据 rating 判断交互类型，这里简化处理
                    "type": "like" if rating >= 4 else "view", 
                    "score": rating, 
                    "timestamp": timestamp # 假设 timestamp 是 datetime 对象
                })
        return interactions

    def _calculate_item_popularity(self, time_window_days: int = 30) -> None:
        """
        计算物品的基础流行度分数。
        基于指定时间窗口内的交互次数。
        """
        print(f"Calculating item popularity for the last {time_window_days} days...")
        item_interaction_counts = Counter()
        cutoff_date = datetime.now() - timedelta(days=time_window_days)

        # --- 修改循环逻辑 --- 
        # 迭代时间戳字典来检查时间窗口
        for user_id, item_timestamps in self.user_item_timestamps.items():
            for item_id, timestamp in item_timestamps.items():
                # 确保 timestamp 是 datetime 对象且在时间窗口内
                if isinstance(timestamp, datetime) and timestamp >= cutoff_date:
                    # 如果在时间窗口内，增加物品的交互计数
                    item_interaction_counts[item_id] += 1 # 简化：只计数，不加权
        # --- 循环逻辑结束 --- 
        
        if not item_interaction_counts:
            print("No interactions found in the time window to calculate popularity.")
            self.item_popularity_scores = {}
            return

        # 归一化处理 (使用 log1p 平滑处理)
        max_count = max(item_interaction_counts.values()) if item_interaction_counts else 1
        # 使用log1p进行归一化，避免极端值影响过大，同时处理0交互的情况
        # 为了让log值有意义，可以将count稍微放大或加1处理
        # 例如，乘以一个系数或者直接对原始count取log
        
        temp_scores = {}
        max_log_score = 0
        for item_id, count in item_interaction_counts.items():
            # 使用 log1p(count) 作为分数基础
            log_score = math.log1p(count) 
            temp_scores[item_id] = log_score
            if log_score > max_log_score:
                max_log_score = log_score

        # 再次归一化到 0-1 区间
        if max_log_score > 0:
             self.item_popularity_scores = {item_id: score / max_log_score 
                                          for item_id, score in temp_scores.items()}
        else:
             self.item_popularity_scores = {item_id: 0.0 for item_id in temp_scores}
             
        print(f"Calculated popularity for {len(self.item_popularity_scores)} items.")
        # print("Sample popularity scores:", dict(list(self.item_popularity_scores.items())[:5])) # 可选：打印样本数据

    def _get_adaptive_popularity_adjustment(self, base_popularity: float, adaptive_factor: float) -> float:
        """
        根据基础流行度和适应因子计算流行度调整值 (乘数)。
        adaptive_factor: -1 (偏好冷门) to 1 (偏好热门)
        返回一个乘数，用于调整原始分数。
        """
        # 基础公式: adjustment = 1.0 + adaptive_factor * influence_function(base_popularity)
        # influence_function 控制流行度影响的强度和方式
        # 使用 log1p 平滑处理 base_popularity (假设 base_popularity 在 0-1 之间)
        # 乘以 0.5 是为了控制调整幅度，可以调整
        influence = 0.5 * math.log1p(base_popularity * 10) # *10 放大一点效果
        
        adjustment_multiplier = 1.0 + adaptive_factor * influence
        
        # 确保调整系数是正数，避免分数变为负数或零 (除非有意为之)
        return max(0.01, adjustment_multiplier) # 最小为0.01，防止完全消除分数

    def _calculate_item_content_similarity(self, item_id1: str, item_id2: str) -> Optional[float]:
        """计算两个物品之间的内容相似度"""
        if item_id1 not in self.item_content_features or item_id2 not in self.item_content_features:
            return None
            
        features1 = self.item_content_features[item_id1]
        features2 = self.item_content_features[item_id2]
        
        # 获取共同特征
        common_features = set(features1.keys()) & set(features2.keys())
        if not common_features:
            return 0.0
            
        # 计算余弦相似度
        dot_product = sum(features1[f] * features2[f] for f in common_features)
        magnitude1 = math.sqrt(sum(features1[f] ** 2 for f in features1))
        magnitude2 = math.sqrt(sum(features2[f] ** 2 for f in features2))
        
        if magnitude1 * magnitude2 == 0:
            return 0.0
            
        return dot_product / (magnitude1 * magnitude2)
    
    def _generate_recommendation_reason(self, user_id: str, item_id: str, sources: List[str]) -> str:
        """生成推荐理由"""
        if not sources:
            return "根据您的个人喜好推荐"
            
        # 物品名称
        item_name = self.item_profiles.get(item_id, {}).get('name', '此物品')
        
        # 生成基于来源的理由
        reasons = []
        
        if 'collaborative' in sources:
            reasons.append("与您喜欢的其他物品相似")
            
        if 'content' in sources:
            # 获取用户喜欢的特征
            liked_features = set()
            if user_id in self.user_item_interactions:
                for liked_item, rating in self.user_item_interactions[user_id].items():
                    if rating > 3 and liked_item in self.item_content_features:
                        for feature, value in self.item_content_features[liked_item].items():
                            if value > 0.7:
                                liked_features.add(feature)
            
            # 与物品特征匹配
            matching_features = []
            if item_id in self.item_content_features:
                for feature, value in self.item_content_features[item_id].items():
                    if value > 0.7 and feature in liked_features:
                        matching_features.append(feature)
            
            if matching_features:
                # 随机选择1-2个特征
                selected_features = random.sample(
                    matching_features, 
                    min(2, len(matching_features))
                )
                reasons.append(f"包含您喜欢的{'/'.join(selected_features)}特征")
            else:
                reasons.append("与您的品味相符")
                
        if 'sequence' in sources:
            reasons.append("基于您的浏览历史")
            
        if 'context' in sources:
            reasons.append("适合您当前的场景")
            
        # 构建完整推荐理由
        if len(reasons) == 1:
            return f"为您推荐{item_name}，{reasons[0]}"
        else:
            # 随机选择两个理由
            selected_reasons = random.sample(reasons, min(2, len(reasons)))
            return f"为您推荐{item_name}，{selected_reasons[0]}，并且{selected_reasons[1]}"
        
    def handle_cold_start_user(self, user_id: str, user_profile: Dict = None, 
                              top_k: int = 10) -> List[Dict]:
        """处理冷启动用户的推荐，增强基于人口统计学特征的初始推荐"""
        # 如果有用户画像，基于画像推荐
        if user_profile:
            self.add_user_profile(user_id, user_profile)
        elif user_id in self.user_profiles:
            user_profile = self.user_profiles[user_id]
        else:
            # 没有用户信息，返回热门物品
            return self.recommend_popular_items(top_k)
            
        # 基于用户画像特征进行内容匹配
        recommendations = []
        
        # 提取用户基本特征
        age = user_profile.get('age', 0)
        gender = user_profile.get('gender', 'unknown')
        interests = user_profile.get('interests', [])
        preferences = user_profile.get('preferences', {})
        
        # 新增人口统计学特征
        location = user_profile.get('location', '')
        education = user_profile.get('education', '')
        occupation = user_profile.get('occupation', '')
        income_level = user_profile.get('income_level', '')
        relationship_status = user_profile.get('relationship_status', '')
        lifestyle = user_profile.get('lifestyle', [])
        
        # 创建人口统计学特征分组
        # 年龄分组
        age_group = ''
        if age > 0:
            if age < 18:
                age_group = 'teen'
            elif age < 25:
                age_group = 'young_adult'
            elif age < 35:
                age_group = 'adult'
            elif age < 50:
                age_group = 'middle_age'
            else:
                age_group = 'senior'
        
        # 收入水平标准化
        normalized_income = ''
        if income_level:
            if isinstance(income_level, str):
                normalized_income = income_level.lower()
            elif isinstance(income_level, (int, float)):
                if income_level < 50000:
                    normalized_income = 'low'
                elif income_level < 100000:
                    normalized_income = 'medium'
                else:
                    normalized_income = 'high'
        
        # 对每个物品评分
        for item_id, item_profile in self.item_profiles.items():
            score = 0.0
            match_reasons = []
            
            # 1. 性别匹配
            if 'target_gender' in item_profile:
                if item_profile['target_gender'] == 'both' or item_profile['target_gender'] == gender:
                    score += 1.0
                    match_reasons.append('性别匹配')
                    
            # 2. 年龄段匹配
            if 'target_age_min' in item_profile and 'target_age_max' in item_profile:
                age_min = item_profile['target_age_min']
                age_max = item_profile['target_age_max']
                if age_min <= age <= age_max:
                    score += 1.0
                    match_reasons.append('年龄匹配')
                
                # 更精细的年龄段匹配
                if 'target_age_group' in item_profile and age_group:
                    if item_profile['target_age_group'] == age_group:
                        score += 0.5
                        match_reasons.append('年龄段精确匹配')
                    
            # 3. 兴趣标签匹配
            if 'tags' in item_profile and interests:
                matching_tags = set(interests) & set(item_profile['tags'])
                if matching_tags:
                    tag_score = len(matching_tags) * 0.5
                    score += tag_score
                    if tag_score > 0.5:
                        match_reasons.append('兴趣匹配')
                    
            # 4. 偏好特征匹配
            if 'features' in item_profile and preferences:
                preference_score = 0
                for pref, value in preferences.items():
                    if pref in item_profile['features']:
                        preference_score += value * item_profile['features'][pref] * 0.3
                score += preference_score
                if preference_score > 0.3:
                    match_reasons.append('偏好匹配')
            
            # 5. 地理位置匹配
            if location and 'target_location' in item_profile:
                target_locations = item_profile['target_location']
                if isinstance(target_locations, list):
                    if location in target_locations:
                        score += 0.8
                        match_reasons.append('位置匹配')
                elif isinstance(target_locations, str):
                    if location == target_locations:
                        score += 0.8
                        match_reasons.append('位置匹配')
            
            # 6. 教育水平匹配
            if education and 'target_education' in item_profile:
                if item_profile['target_education'] == education:
                    score += 0.6
                    match_reasons.append('教育背景匹配')
            
            # 7. 职业匹配
            if occupation and 'target_occupation' in item_profile:
                target_occupations = item_profile['target_occupation']
                if isinstance(target_occupations, list):
                    if occupation in target_occupations:
                        score += 0.7
                        match_reasons.append('职业匹配')
                elif isinstance(target_occupations, str):
                    if occupation == target_occupations:
                        score += 0.7
                        match_reasons.append('职业匹配')
            
            # 8. 收入水平匹配
            if normalized_income and 'target_income' in item_profile:
                if item_profile['target_income'] == normalized_income:
                    score += 0.5
                    match_reasons.append('收入水平匹配')
            
            # 9. 关系状态匹配
            if relationship_status and 'target_relationship_status' in item_profile:
                if item_profile['target_relationship_status'] == relationship_status:
                    score += 0.6
                    match_reasons.append('关系状态匹配')
            
            # 10. 生活方式匹配
            if lifestyle and 'target_lifestyle' in item_profile:
                target_lifestyle = item_profile['target_lifestyle']
                if isinstance(target_lifestyle, list) and isinstance(lifestyle, list):
                    matching_lifestyle = set(lifestyle) & set(target_lifestyle)
                    lifestyle_score = len(matching_lifestyle) * 0.3
                    score += lifestyle_score
                    if lifestyle_score > 0.3:
                        match_reasons.append('生活方式匹配')
            
            # 11. 社会群体匹配
            if 'social_group' in user_profile and 'target_social_group' in item_profile:
                if user_profile['social_group'] == item_profile['target_social_group']:
                    score += 0.5
                    match_reasons.append('社会群体匹配')
                
            # 12. 考虑物品流行度（热度）
            if item_id in self.item_popularity:
                popularity = math.log1p(self.item_popularity[item_id])
                pop_weight = 0.2
                # 如果用户特征非常少，增加流行度权重
                if len(match_reasons) <= 1:
                    pop_weight = 0.5
                score += popularity * pop_weight
                if popularity > 1.0:
                    match_reasons.append('热门推荐')
                
            # 如果得分大于0，添加到推荐结果
            if score > 0:
                recommendations.append({
                    'item_id': item_id,
                    'score': float(score),
                    'source': 'cold_start',
                    'match_reasons': match_reasons
                })
                
        # 按得分排序
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        
        # 为了增加多样性，应用简单的再排序
        if len(recommendations) > top_k * 2:
            final_recommendations = self._diversify_cold_start_recommendations(
                recommendations[:top_k * 2], top_k
            )
        else:
            final_recommendations = recommendations[:top_k]
        
        # 为每个推荐添加详细信息
        for rec in final_recommendations:
            item_id = rec['item_id']
            if item_id in self.item_profiles:
                rec['details'] = self.item_profiles[item_id]
                
                # 添加推荐理由
                match_reasons = rec.get('match_reasons', [])
                if match_reasons:
                    # 选择最重要的1-2个原因
                    selected_reasons = match_reasons[:min(2, len(match_reasons))]
                    rec['reason'] = f"推荐理由: {' 和 '.join(selected_reasons)}"
                else:
                    tags = self.item_profiles[item_id].get('tags', [])
                    if interests and tags:
                        matching_tags = set(interests) & set(tags)
                        if matching_tags:
                            selected_tags = list(matching_tags)[:2]
                            rec['reason'] = f"与您的{'/'.join(selected_tags)}兴趣相关"
                        else:
                            rec['reason'] = "基于您的个人资料推荐"
                    else:
                        rec['reason'] = "可能适合您的品味"
                    
        return final_recommendations
    
    def _determine_user_popularity_preference(self, user_id: str) -> float:
        """
        根据用户历史行为推断用户对流行内容的偏好程度
        
        参数:
            user_id: 用户ID
            
        返回:
            float: 范围从-1.0（偏好冷门）到1.0（偏好热门）的值
                  0.0表示中性或无明显偏好
        """
        if user_id not in self.user_item_interactions:
            return 0.0  # 默认为中性

        # 确保流行度分数已计算
        if not hasattr(self, 'item_popularity_scores') or not self.item_popularity_scores:
            self._calculate_item_popularity()
            
        # 获取用户交互的所有物品
        user_items = list(self.user_item_interactions[user_id].keys())
        if not user_items:
            return 0.0
            
        # 获取这些物品的流行度分数
        item_popularities = [self.item_popularity_scores.get(item_id, 0.0) for item_id in user_items]
        if not item_popularities:
            return 0.0
            
        # 计算用户交互物品的平均流行度
        avg_popularity = sum(item_popularities) / len(item_popularities)
        
        # 计算系统中所有物品的平均流行度作为参考值
        if not self.item_popularity_scores:
            system_avg = 0.5  # 默认中间值
        else:
            system_avg = sum(self.item_popularity_scores.values()) / len(self.item_popularity_scores)
            
        # 计算用户偏好指数（归一化到-1到1之间）
        # 公式：2 * (用户平均流行度 - 系统平均流行度) / 系统平均流行度
        # 限制在-1到1范围内
        preference = 2 * (avg_popularity - system_avg) / max(system_avg, 0.01)
        preference = max(-1.0, min(1.0, preference))
        
        return preference

    def load_data(self,
                  users: List[Dict[str, Any]],
                  items: List[Dict[str, Any]],
                  user_item_interactions: List[Dict[str, Any]]) -> None:
        """
        加载完整的数据集到推荐引擎。
        会清空引擎中的现有数据。
        """
        print(f"[RecommendationEngine] 开始加载数据: {len(users)} 用户, {len(items)} 物品, {len(user_item_interactions)} 交互...")

        # <-- 添加调试日志：打印输入交互数据的前几项 -->
        print("[RecommendationEngine Debug] 检查传入的 user_item_interactions 前 3 项:")
        for i, interaction_debug in enumerate(user_item_interactions[:3]):
             print(f"  Item {i}: {interaction_debug}")
             if 'timestamp' in interaction_debug:
                  print(f"    - Timestamp type: {type(interaction_debug['timestamp'])}")
             else:
                  print("    - Timestamp field missing")
        # <-- 结束调试日志 -->

        # 1. 清空现有数据
        print("[RecommendationEngine] 清空现有数据...")
        self.user_item_matrix = None
        self.user_factors = None
        self.item_factors = None
        self.user_mapping = {}
        self.item_mapping = {}
        self.reverse_user_mapping = {}
        self.reverse_item_mapping = {}
        self.item_content_features = {} # 假设内容特征也需要重新加载
        self.user_profiles = {}
        self.item_profiles = {}
        self.user_item_interactions = {}
        self.item_popularity = {}
        self.user_item_timestamps = {}
        self.user_similarity_matrix = None
        self.item_similarity_matrix = None
        self.content_similarity_matrix = None
        self.item_context_features = {} # 假设上下文特征也需重新加载
        self.user_sequence_data = {}
        self.item_popularity_scores = {}

        # 2. 加载用户画像
        print("[RecommendationEngine] 加载用户画像...")
        for user_data in users:
            user_id = user_data.get('user_id')
            if user_id:
                self.add_user_profile(user_id, user_data)
        print(f"[RecommendationEngine] 完成加载 {len(self.user_profiles)} 个用户画像。") # <-- 已有此日志
        # --- 在加载用户循环后添加日志 ---
        print(f"[RecommendationEngine Debug] After user loop, self.user_profiles size: {len(self.user_profiles)}")
        # --- 结束日志 ---

        # 3. 加载物品画像 (并提取内容特征，如果需要)
        print("[RecommendationEngine] 加载物品画像...")
        for item_data in items:
            item_id = item_data.get('item_id')
            if item_id:
                self.add_item_profile(item_id, item_data)
                # 简单示例：将物品的 tags 作为内容特征
                tags = item_data.get('tags')
                if isinstance(tags, list):
                    # 将标签转换为 one-hot 形式或简单的存在性特征
                    content_features = {f"tag_{tag}": 1 for tag in tags}
                    self.add_item_content_features(item_id, content_features)
        print(f"[RecommendationEngine] 完成加载 {len(self.item_profiles)} 个物品画像和 {len(self.item_content_features)} 个物品内容特征。")

        # 4. 加载用户-物品交互，并提取评分数据
        print("[RecommendationEngine] 加载用户-物品交互...")
        ratings_data = []
        interaction_count = 0
        for interaction in user_item_interactions:
            user_id = interaction.get('user_id')
            item_id = interaction.get('item_id')
            interaction_type = interaction.get('interaction_type')
            score = interaction.get('score') # 由 ComprehensiveDataGenerator 生成
            rating_value = interaction.get('rating_value') # rate 类型有此字段
            timestamp = interaction.get('timestamp') # 直接获取，预期是 datetime 对象

            # <-- 添加调试日志：打印每次循环的时间戳类型 -->
            # if timestamp:
            #      print(f"[RecommendationEngine Debug] Processing interaction ({user_id}, {item_id}). Timestamp type: {type(timestamp)}")
            # else:
            #      print(f"[RecommendationEngine Debug] Processing interaction ({user_id}, {item_id}). Timestamp is None.")
            # <-- 结束调试日志 -->

            # if not all([user_id, item_id, interaction_type, timestamp]): # 注意：timestamp 不能为空
            #     print(f"[RecommendationEngine] 跳过不完整的交互记录: {interaction}")
            #     continue # <-- Skips if timestamp is None (or other fields missing)

            # --- 添加 internal_rating 定义 --- 
            internal_rating = score if score is not None else 1.0 # 使用 score 或默认值
            # --- 结束定义 --- 
            
            # 使用引擎自带的方法添加交互，确保状态一致性
            self.add_user_item_interaction(user_id, item_id, internal_rating, timestamp)
            interaction_count += 1

            # 提取用于矩阵分解的评分
            rating_for_matrix = None
            if interaction_type == 'rate' and rating_value is not None:
                rating_for_matrix = float(rating_value)
            elif interaction_type == 'like':
                 rating_for_matrix = 4.0
            elif interaction_type == 'purchase':
                 rating_for_matrix = 5.0
            # 可以根据需要添加更多映射规则
            
            if rating_for_matrix is not None and user_id in self.user_profiles and item_id in self.item_profiles:
                 ratings_data.append({
                     'user_id': user_id,
                     'item_id': item_id,
                     'rating': rating_for_matrix,
                     'timestamp': timestamp # 保留时间戳可能有用
                 })
        print(f"[RecommendationEngine] 完成处理 {interaction_count} 条有效交互。提取了 {len(ratings_data)} 条评分记录用于矩阵构建。")

        # 5. 构建用户-物品矩阵
        if ratings_data:
            print("[RecommendationEngine] 构建用户-物品评分矩阵...")
            try:
                self.build_user_item_matrix(ratings_data)
                print(f"[RecommendationEngine] 矩阵构建完成，维度: {self.user_item_matrix.shape}")
                print(f"[RecommendationEngine] 用户映射数量: {len(self.user_mapping)}, 物品映射数量: {len(self.item_mapping)}")
            except Exception as e:
                print(f"[RecommendationEngine] 构建用户-物品矩阵时出错: {e}")
        else:
            print("[RecommendationEngine] 没有提取到足够用于矩阵构建的评分数据。")

        # 6. 重新计算物品流行度分数 (基于加载的所有交互)
        print("[RecommendationEngine] 计算物品流行度...")
        self._calculate_item_popularity() # 调用内部方法更新流行度分数
        print(f"[RecommendationEngine] 完成计算 {len(self.item_popularity_scores)} 个物品的流行度。")

        # self.calculate_content_similarity()
        
        # --- 取消注释以启用模型训练 ---
        if self.user_item_matrix is not None and self.user_item_matrix.shape[0] > 0 and self.user_item_matrix.shape[1] > 0:
            print("[RecommendationEngine] 开始训练矩阵分解模型...")
            try:
                # 确保训练前矩阵不为空
                self.train_matrix_factorization(n_factors=20, n_iterations=10) # 使用较少迭代次数快速训练
                print("[RecommendationEngine] 矩阵分解模型训练完成。")
            except Exception as e:
                print(f"[RecommendationEngine] 训练矩阵分解模型时出错: {e}")
        elif self.user_item_matrix is not None:
             print("[RecommendationEngine] 跳过矩阵分解训练，因为矩阵维度不足或为空。")
        # --- 模型训练结束 ---

        # 7. 计算内容相似度 (如果需要)
        print("[RecommendationEngine] 计算内容相似度...")
        try:
             self.calculate_content_similarity() # <-- 确保被调用
             if self.content_similarity_matrix is not None:
                  print(f"[RecommendationEngine] 内容相似度矩阵计算完成，维度: {self.content_similarity_matrix.shape}")
             else:
                  print("[RecommendationEngine] 内容相似度矩阵未能生成 (可能缺少内容特征)。")
        except Exception as e:
             print(f"[RecommendationEngine] 计算内容相似度时出错: {e}")

        # 8. 打印最终状态确认
        if self.user_factors is not None:
             print(f"[RecommendationEngine] 确认: user_factors 维度: {self.user_factors.shape}")
        else:
             print("[RecommendationEngine] 确认: user_factors 未生成。")
        if self.item_factors is not None:
             print(f"[RecommendationEngine] 确认: item_factors 维度: {self.item_factors.shape}")
        else:
             print("[RecommendationEngine] 确认: item_factors 未生成。")

        # --- 在方法末尾添加日志 ---
        print(f"[RecommendationEngine Debug] End of load_data method, self.user_profiles size: {len(self.user_profiles)}")
        # --- 结束日志 ---
        print("[RecommendationEngine] 数据加载过程完成。")

    def calculate_content_similarity(self) -> np.ndarray:
        """计算物品内容相似度矩阵"""
        # 如果物品内容特征为空，返回None
        if not self.item_content_features:
            return None
            
        # 获取所有物品ID和特征
        item_ids = list(self.item_content_features.keys())
        
        # 构建特征矩阵
        feature_names = set()
        for features in self.item_content_features.values():
            feature_names.update(features.keys())
        
        feature_names = list(feature_names)
        feature_matrix = np.zeros((len(item_ids), len(feature_names)))
        
        # 填充特征矩阵
        for i, item_id in enumerate(item_ids):
            features = self.item_content_features[item_id]
            for j, feature_name in enumerate(feature_names):
                feature_matrix[i, j] = features.get(feature_name, 0)
        
        # 标准化特征
        scaler = StandardScaler()
        feature_matrix = scaler.fit_transform(feature_matrix)
        
        # 计算余弦相似度
        similarity_matrix = cosine_similarity(feature_matrix)
        
        # 保存物品ID到索引的映射
        item_to_idx = {item_id: i for i, item_id in enumerate(item_ids)}
        
        # 保存相似度矩阵和映射关系
        self.content_similarity_matrix = similarity_matrix
        
        return similarity_matrix
        
    # ... (文件末尾)