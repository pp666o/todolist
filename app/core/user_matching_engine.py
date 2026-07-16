import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any, Union
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler
import networkx as nx
from collections import Counter
import random
import math
from datetime import datetime

# 定义简单的性格维度
PERSONALITY_DIMENSIONS = ["extraversion", "agreeableness", "conscientiousness", "neuroticism", "openness"]

class UserMatchingEngine:
    def __init__(self):
        self.user_profiles = {}
        self.item_profiles = {}
        self.user_item_interactions = {}
        self.user_feature_matrix = None
        self.user_feature_names = []
        self.item_feature_matrix = None
        self.item_feature_names = []
        self.user_similarity_matrix = None
        self.item_similarity_matrix = None
        self.preference_graph = nx.DiGraph()
        self.scaler = StandardScaler()
        
    def add_user_profile(self, user_id: str, profile: Dict) -> None:
        """添加用户资料"""
        # 确保为新用户提取或生成性格特征
        if 'personality_traits' not in profile:
             profile['personality_traits'] = self.extract_personality_traits(user_id, profile) # 传入profile
        self.user_profiles[user_id] = profile
        # 更新用户特征矩阵
        self._update_user_feature_matrix()
        
    def add_batch_user_profiles(self, profiles: List[Dict]) -> None:
        """批量添加用户资料"""
        for profile in profiles:
            user_id = profile.get("user_id")
            if user_id:
                 # 确保为新用户提取或生成性格特征
                 if 'personality_traits' not in profile:
                      profile['personality_traits'] = self.extract_personality_traits(user_id, profile) # 传入profile
                 self.user_profiles[user_id] = profile
        
        # 更新用户特征矩阵
        self._update_user_feature_matrix()
        
    def add_item_profile(self, item_id: str, profile: Dict) -> None:
        """添加物品资料"""
        self.item_profiles[item_id] = profile
        # 更新物品特征矩阵
        self._update_item_feature_matrix()
        
    def add_batch_item_profiles(self, profiles: List[Dict]) -> None:
        """批量添加物品资料"""
        for profile in profiles:
            item_id = profile.get("item_id")
            if item_id:
                self.item_profiles[item_id] = profile
        
        # 更新物品特征矩阵
        self._update_item_feature_matrix()
        
    def add_user_item_interaction(self, user_id: str, item_id: str, 
                                interaction_type: str, score: float = 1.0) -> None:
        """添加用户-物品交互"""
        if user_id not in self.user_item_interactions:
            self.user_item_interactions[user_id] = {}
        
        if item_id not in self.user_item_interactions[user_id]:
            self.user_item_interactions[user_id][item_id] = []
            
        self.user_item_interactions[user_id][item_id].append({
            "type": interaction_type,
            "score": score
        })
        
        # 更新偏好图
        self._update_preference_graph(user_id, item_id, score)
        
    def _update_user_feature_matrix(self) -> None:
        """更新用户特征矩阵"""
        if not self.user_profiles:
            return
            
        # 收集所有特征名
        all_features = set()
        for profile in self.user_profiles.values():
            all_features.update(profile.keys())
            
        # 移除用户ID和非数值特征
        non_feature_fields = {"user_id", "name", "email", "phone", "address", "description"}
        features = [f for f in all_features if f not in non_feature_fields]
        self.user_feature_names = sorted(features)
        
        # 构建特征矩阵
        user_ids = list(self.user_profiles.keys())
        feature_matrix = []
        
        for user_id in user_ids:
            profile = self.user_profiles[user_id]
            features = []
            
            for feature_name in self.user_feature_names:
                # 数值特征直接使用
                if feature_name in profile and isinstance(profile[feature_name], (int, float)):
                    features.append(profile[feature_name])
                # 类别特征转为one-hot
                elif feature_name in profile and isinstance(profile[feature_name], str):
                    # 简单处理:性别转为0/1，其他特征暂时用0
                    if feature_name == "gender":
                        features.append(1 if profile[feature_name].lower() in ["male", "m", "男"] else 0)
                    else:
                        # 其他分类特征，可以扩展处理
                        features.append(0)
                else:
                    features.append(0)  # 缺失值填充为0
                    
            feature_matrix.append(features)
        
        # 转换为numpy数组并标准化
        if feature_matrix:
            self.user_feature_matrix = self.scaler.fit_transform(np.array(feature_matrix))
            
            # 计算用户相似度矩阵
            self.user_similarity_matrix = cosine_similarity(self.user_feature_matrix)
        
    def _update_item_feature_matrix(self) -> None:
        """更新物品特征矩阵"""
        if not self.item_profiles:
            return
            
        # 收集所有特征名
        all_features = set()
        for profile in self.item_profiles.values():
            all_features.update(profile.keys())
            
        # 移除物品ID和非数值特征
        non_feature_fields = {"item_id", "name", "description", "category"}
        features = [f for f in all_features if f not in non_feature_fields]
        self.item_feature_names = sorted(features)
        
        # 构建特征矩阵
        item_ids = list(self.item_profiles.keys())
        feature_matrix = []
        
        for item_id in item_ids:
            profile = self.item_profiles[item_id]
            features = []
            
            for feature_name in self.item_feature_names:
                if feature_name in profile and isinstance(profile[feature_name], (int, float)):
                    features.append(profile[feature_name])
                else:
                    features.append(0)  # 缺失值填充为0
                    
            feature_matrix.append(features)
        
        # 转换为numpy数组并标准化
        if feature_matrix:
            self.item_feature_matrix = self.scaler.fit_transform(np.array(feature_matrix))
            
            # 计算物品相似度矩阵
            self.item_similarity_matrix = cosine_similarity(self.item_feature_matrix)
    
    def _update_preference_graph(self, user_id: str, item_id: str, score: float) -> None:
        """更新偏好图"""
        # 添加节点
        if user_id not in self.preference_graph:
            self.preference_graph.add_node(user_id, type='user')
        if item_id not in self.preference_graph:
            self.preference_graph.add_node(item_id, type='item')
            
        # 添加/更新边权重
        if self.preference_graph.has_edge(user_id, item_id):
            # 已存在边，更新权重（累积）
            current_weight = self.preference_graph[user_id][item_id]['weight']
            self.preference_graph[user_id][item_id]['weight'] = current_weight + score
        else:
            # 新建边
            self.preference_graph.add_edge(user_id, item_id, weight=score)
    
    def calculate_user_similarity(self, user_id1: str, user_id2: str, 
                                personality_weight: float = 0.3) -> float:
        """计算两个用户之间的相似度，结合特征相似度和性格兼容性"""
        if user_id1 not in self.user_profiles or user_id2 not in self.user_profiles:
            return 0.0
            
        # 1. 计算基于特征的相似度
        if self.user_similarity_matrix is None:
            self._update_user_feature_matrix()
            if self.user_similarity_matrix is None: # 如果更新后仍然为None
                 return 0.0 
            
        user_ids = list(self.user_profiles.keys())
        try:
            idx1 = user_ids.index(user_id1)
            idx2 = user_ids.index(user_id2)
            feature_similarity = float(self.user_similarity_matrix[idx1, idx2])
        except ValueError:
            # 如果用户ID不在索引中（理论上不应发生，因为前面检查过）
            return 0.0
        except IndexError:
             # 如果索引超出范围
             return 0.0

        # 2. 计算性格兼容性
        traits1 = self.user_profiles[user_id1].get('personality_traits', {})
        traits2 = self.user_profiles[user_id2].get('personality_traits', {})
        
        # 如果没有性格特征，则兼容性为中性值(0.5)或只用特征相似度
        if not traits1 or not traits2:
             personality_compatibility = 0.5 # 或者可以设为0，让权重决定影响
        else:
             personality_compatibility = self.calculate_personality_compatibility(traits1, traits2)

        # 3. 结合两种相似度
        combined_similarity = (1 - personality_weight) * feature_similarity + personality_weight * personality_compatibility
        
        return combined_similarity

    def extract_personality_traits(self, user_id: str, profile: Dict) -> Dict[str, float]:
         """
         从用户数据中提取或模拟性格特征 (Big Five 模型)
         这是一个简化的模拟实现，实际应用中需要更复杂的模型。
         """
         # 1. 检查Profile中是否已存在
         if 'personality_traits' in profile and isinstance(profile['personality_traits'], dict):
             # 验证结构是否符合预期
             if all(dim in profile['personality_traits'] for dim in PERSONALITY_DIMENSIONS):
                 return profile['personality_traits']

         # 2. 基于启发式规则模拟生成
         traits = {}
         
         # 示例: 基于互动频率和类型推断外向性
         extraversion_score = 0.5 # 默认值
         if user_id in self.user_item_interactions:
             num_interactions = sum(len(items) for items in self.user_item_interactions[user_id].values())
             # 互动越多，可能越外向 (简单假设)
             extraversion_score = min(1.0, 0.3 + num_interactions / 50.0) # 假设50次互动达到较高外向性
         traits["extraversion"] = extraversion_score

         # 示例: 基于喜欢物品的多样性推断开放性
         openness_score = 0.5
         if user_id in self.user_item_interactions:
             liked_item_ids = list(self.user_item_interactions[user_id].keys())
             if len(liked_item_ids) > 1:
                 categories = set()
                 for item_id in liked_item_ids:
                     if item_id in self.item_profiles and 'category' in self.item_profiles[item_id]:
                         categories.add(self.item_profiles[item_id]['category'])
                 # 喜欢类别越多，可能越开放
                 openness_score = min(1.0, 0.3 + len(categories) / 10.0) # 假设10个不同类别达到较高开放性
         traits["openness"] = openness_score

         # 示例: 基于Profile完整度推断尽责性
         conscientiousness_score = 0.5
         profile_fields = [k for k, v in profile.items() if v is not None and k != 'user_id']
         total_possible_fields = len(self.user_feature_names) + 5 # 假设基础字段数量
         if total_possible_fields > 0:
             completeness = len(profile_fields) / total_possible_fields
             conscientiousness_score = min(1.0, 0.2 + completeness * 0.8)
         traits["conscientiousness"] = conscientiousness_score

         # 示例: 宜人性 和 神经质性 - 简单随机或默认
         traits["agreeableness"] = profile.get('agreeableness', round(random.uniform(0.3, 0.7), 2)) # 如果profile有就用，否则随机
         traits["neuroticism"] = profile.get('neuroticism', round(random.uniform(0.2, 0.6), 2))

         # 确保所有维度都存在
         for dim in PERSONALITY_DIMENSIONS:
             if dim not in traits:
                 traits[dim] = 0.5 # 默认值
             # 限制在0-1范围
             traits[dim] = max(0.0, min(1.0, traits[dim]))
             
         return traits

    def calculate_personality_compatibility(self, traits1: Dict[str, float], traits2: Dict[str, float]) -> float:
         """
         计算基于Big Five模型的性格兼容性。
         模型假设：开放性、宜人性、尽责性相似较好；外向性互补较好；神经质性都较低较好。
         这是一个简化的模型。
         """
         compatibility_score = 0.0
         num_dims = 0
         
         # 相似性维度: Openness, Agreeableness, Conscientiousness
         for dim in ["openness", "agreeableness", "conscientiousness"]:
             if dim in traits1 and dim in traits2:
                 # 差异越小越好
                 similarity = 1.0 - abs(traits1[dim] - traits2[dim])
                 compatibility_score += similarity
                 num_dims += 1
                 
         # 互补性维度: Extraversion
         if "extraversion" in traits1 and "extraversion" in traits2:
             # 一个高一个低，或都中等较好 (峰值在差异0.5左右)
             complementarity = 1.0 - abs(abs(traits1["extraversion"] - traits2["extraversion"]) - 0.5) * 2
             compatibility_score += complementarity
             num_dims += 1

         # 负面维度: Neuroticism (都低比较好)
         if "neuroticism" in traits1 and "neuroticism" in traits2:
             # 分数越低越好，计算负相关的相似度 (1 - 平均值)
             low_score_similarity = 1.0 - (traits1["neuroticism"] + traits2["neuroticism"]) / 2.0
             compatibility_score += low_score_similarity
             num_dims += 1

         if num_dims == 0:
             return 0.5 # 无法计算时返回中性值

         # 平均得分
         final_score = compatibility_score / num_dims
         return max(0.0, min(1.0, final_score)) # 确保在0-1之间
    
    def calculate_complementarity(self, user_id1: str, user_id2: str) -> Dict:
        """计算两个用户的互补性"""
        if user_id1 not in self.user_profiles or user_id2 not in self.user_profiles:
            return {"complementarity_score": 0.0}
            
        profile1 = self.user_profiles[user_id1]
        profile2 = self.user_profiles[user_id2]
        
        # 计算互补性指标
        # 1. 性别互补
        gender_complementary = 0.0
        if "gender" in profile1 and "gender" in profile2:
            gender1 = profile1["gender"].lower()
            gender2 = profile2["gender"].lower()
            if (gender1 in ["male", "m", "男"] and gender2 in ["female", "f", "女"]) or \
               (gender2 in ["male", "m", "男"] and gender1 in ["female", "f", "女"]):
                gender_complementary = 1.0
                
        # 2. 兴趣互补性（兴趣交集与差集的比例）
        interest_complementary = 0.0
        if "interests" in profile1 and "interests" in profile2:
            interests1 = set(profile1["interests"]) if isinstance(profile1["interests"], list) else set()
            interests2 = set(profile2["interests"]) if isinstance(profile2["interests"], list) else set()
            
            intersection = interests1.intersection(interests2)
            union = interests1.union(interests2)
            
            # 部分相同，部分不同的兴趣最为互补
            if union:
                interest_complementary = (1 - abs(0.5 - len(intersection) / len(union)) * 2)
        
        # 3. 年龄互补性
        age_complementary = 0.0
        if "age" in profile1 and "age" in profile2:
            age1 = profile1["age"]
            age2 = profile2["age"]
            age_diff = abs(age1 - age2)
            
            # 年龄差在5-10岁之间时互补性最高
            if age_diff <= 15:
                age_complementary = 1.0 - age_diff / 15
        
        # 综合互补性评分
        complementarity_score = (gender_complementary * 0.4 + 
                               interest_complementary * 0.4 + 
                               age_complementary * 0.2)
                               
        return {
            "complementarity_score": float(complementarity_score),
            "gender_complementary": float(gender_complementary),
            "interest_complementary": float(interest_complementary),
            "age_complementary": float(age_complementary)
        }
    
    def find_common_interests(self, user_id1: str, user_id2: str) -> List[str]:
        """查找两个用户的共同兴趣"""
        common_interests = []
        
        if user_id1 in self.user_profiles and user_id2 in self.user_profiles:
            profile1 = self.user_profiles[user_id1]
            profile2 = self.user_profiles[user_id2]
            
            if "interests" in profile1 and "interests" in profile2:
                interests1 = set(profile1["interests"]) if isinstance(profile1["interests"], list) else set()
                interests2 = set(profile2["interests"]) if isinstance(profile2["interests"], list) else set()
                
                common_interests = list(interests1.intersection(interests2))
        
        return common_interests
    
    def find_potential_matches(self, user_id: str, 
                             top_k: int = 10,
                             min_similarity: float = 0.3,
                             min_complementarity: float = 0.3,
                             gender_filter: Optional[str] = None) -> List[Dict]:
        """查找用户的潜在匹配对象"""
        if user_id not in self.user_profiles:
            return []
            
        matches = []
        user_profile = self.user_profiles[user_id]
        
        for other_id, other_profile in self.user_profiles.items():
            if other_id == user_id:
                continue
                
            # 性别过滤
            if gender_filter and other_profile.get("gender", "").lower() != gender_filter.lower():
                continue
                
            # 计算相似度
            similarity = self.calculate_user_similarity(user_id, other_id)
            
            # 计算互补性
            complementarity = self.calculate_complementarity(user_id, other_id)
            
            # 综合得分
            match_score = (similarity * 0.4 + complementarity["complementarity_score"] * 0.6)
            
            # 过滤阈值
            if similarity >= min_similarity and complementarity["complementarity_score"] >= min_complementarity:
                matches.append({
                    "user_id": other_id,
                    "similarity": float(similarity),
                    "complementarity": complementarity["complementarity_score"],
                    "match_score": float(match_score),
                    "common_interests": self.find_common_interests(user_id, other_id)
                })
        
        # 按匹配得分排序
        matches.sort(key=lambda x: x["match_score"], reverse=True)
        
        return matches[:top_k]
    
    def recommend_items_for_pair(self, user_id1: str, user_id2: str, 
                               item_type: Optional[str] = None, 
                               top_k: int = 10) -> List[Dict]:
        """为一对用户推荐共同的物品/活动"""
        if user_id1 not in self.user_profiles or user_id2 not in self.user_profiles:
            return []
            
        # 获取两个用户的兴趣和互动历史
        common_interests = self.find_common_interests(user_id1, user_id2)
        
        # 获取两个用户各自喜欢的物品
        user1_items = set(self.user_item_interactions.get(user_id1, {}).keys())
        user2_items = set(self.user_item_interactions.get(user_id2, {}).keys())
        
        # 计算互补性
        complementarity = self.calculate_complementarity(user_id1, user_id2)
        
        # 为两人推荐共同的物品
        recommendations = []
        
        # 策略1: 基于共同兴趣的物品
        interest_based_items = []
        for item_id, profile in self.item_profiles.items():
            # 跳过已经交互过的物品
            if item_id in user1_items or item_id in user2_items:
                continue
                
            # 物品类型过滤
            if item_type and profile.get("type") != item_type:
                continue
                
            # 计算物品与共同兴趣的匹配度
            match_score = 0.0
            
            # 检查物品标签与共同兴趣的匹配
            item_tags = profile.get("tags", [])
            if item_tags and common_interests:
                # 计算交集大小
                matching_tags = len(set(item_tags).intersection(common_interests))
                match_score += matching_tags / len(item_tags) if item_tags else 0
            
            # 添加推荐物品
            if match_score > 0:
                interest_based_items.append({
                    "item_id": item_id,
                    "score": match_score,
                    "source": "common_interests"
                })
                
        # 策略2: 基于协同过滤的物品
        cf_items = []
        all_user_items = user1_items.union(user2_items)
        
        for item_id, profile in self.item_profiles.items():
            if item_id in all_user_items:
                continue
                
            # 物品类型过滤
            if item_type and profile.get("type") != item_type:
                continue
                
            # 计算与用户已交互物品的相似度
            similarity_scores = []
            
            for user_item in all_user_items:
                if self.item_similarity_matrix is not None:
                    item_ids = list(self.item_profiles.keys())
                    if item_id in item_ids and user_item in item_ids:
                        idx1 = item_ids.index(item_id)
                        idx2 = item_ids.index(user_item)
                        similarity_scores.append(self.item_similarity_matrix[idx1, idx2])
            
            # 取最高相似度作为得分
            if similarity_scores:
                cf_items.append({
                    "item_id": item_id,
                    "score": float(max(similarity_scores)),
                    "source": "collaborative_filtering"
                })
                
        # 策略3: 基于用户画像的物品
        profile_items = []
        
        for item_id, profile in self.item_profiles.items():
            if item_id in all_user_items:
                continue
                
            # 物品类型过滤
            if item_type and profile.get("type") != item_type:
                continue
                
            # 根据物品针对人群特征来评分
            target_gender = profile.get("target_gender")
            target_age_min = profile.get("target_age_min")
            target_age_max = profile.get("target_age_max")
            
            # 检查适合情侣/夫妻的特征
            couples_score = profile.get("couples_score", 0)
            
            # 性别匹配
            gender_match = 0.0
            if target_gender:
                if target_gender == "both":
                    gender_match = 1.0
                elif (target_gender == "male" and self.user_profiles[user_id1].get("gender") in ["male", "m", "男"] and
                      self.user_profiles[user_id2].get("gender") in ["female", "f", "女"]):
                    gender_match = 1.0
                elif (target_gender == "female" and self.user_profiles[user_id1].get("gender") in ["female", "f", "女"] and
                      self.user_profiles[user_id2].get("gender") in ["male", "m", "男"]):
                    gender_match = 1.0
            else:
                gender_match = 0.5  # 无特定目标性别
                
            # 年龄匹配
            age_match = 0.0
            user1_age = self.user_profiles[user_id1].get("age", 0)
            user2_age = self.user_profiles[user_id2].get("age", 0)
            
            if target_age_min and target_age_max:
                if target_age_min <= user1_age <= target_age_max and target_age_min <= user2_age <= target_age_max:
                    age_match = 1.0
                elif target_age_min <= (user1_age + user2_age) / 2 <= target_age_max:
                    age_match = 0.7
            else:
                age_match = 0.5  # 无特定目标年龄
                
            # 综合得分
            profile_score = (gender_match * 0.3 + age_match * 0.3 + couples_score * 0.4)
            
            if profile_score > 0:
                profile_items.append({
                    "item_id": item_id,
                    "score": float(profile_score),
                    "source": "user_profile"
                })
                
        # 组合所有策略的结果
        all_items = interest_based_items + cf_items + profile_items
        
        # 为每个物品计算最终得分
        item_scores = {}
        for item in all_items:
            item_id = item["item_id"]
            if item_id not in item_scores:
                item_scores[item_id] = {
                    "item_id": item_id,
                    "name": self.item_profiles[item_id].get("name", ""),
                    "score": 0.0,
                    "sources": []
                }
            
            # 累加得分（不同策略可以有不同权重）
            source_weight = {
                "common_interests": 0.5,
                "collaborative_filtering": 0.3,
                "user_profile": 0.2
            }
            
            weight = source_weight.get(item["source"], 0.1)
            item_scores[item_id]["score"] += item["score"] * weight
            item_scores[item_id]["sources"].append(item["source"])
        
        # 转换为列表并排序
        recommendations = list(item_scores.values())
        recommendations.sort(key=lambda x: x["score"], reverse=True)
        
        # 添加物品详情
        for rec in recommendations[:top_k]:
            item_id = rec["item_id"]
            if item_id in self.item_profiles:
                rec["details"] = self.item_profiles[item_id]
                
                # 添加推荐理由
                rec["reason"] = self._generate_recommendation_reason(
                    user_id1, user_id2, item_id, rec["sources"], common_interests
                )
        
        return recommendations[:top_k]
    
    def _generate_recommendation_reason(self, user_id1: str, user_id2: str, 
                                      item_id: str, sources: List[str],
                                      common_interests: List[str]) -> str:
        """生成推荐理由"""
        reasons = []
        
        item_name = self.item_profiles[item_id].get("name", "此项目")
        
        if "common_interests" in sources and common_interests:
            # 随机选择1-2个共同兴趣作为理由
            selected_interests = random.sample(
                common_interests, 
                min(2, len(common_interests))
            )
            reasons.append(f"基于你们共同的{'/'.join(selected_interests)}兴趣")
            
        if "collaborative_filtering" in sources:
            reasons.append("与你们之前喜欢的内容相似")
            
        if "user_profile" in sources:
            # 检查是否适合情侣
            couples_score = self.item_profiles[item_id].get("couples_score", 0)
            if couples_score > 0.7:
                reasons.append("特别适合情侣/伴侣共同体验")
            elif couples_score > 0.4:
                reasons.append("适合两人一起参与")
                
        # 构建完整推荐理由
        if not reasons:
            return f"推荐{item_name}，可能适合你们共同体验"
            
        if len(reasons) == 1:
            return f"推荐{item_name}，{reasons[0]}"
        else:
            return f"推荐{item_name}，{reasons[0]}，并且{reasons[1]}"
            
    def get_relationship_compatibility(self, user_id1: str, user_id2: str) -> Dict:
        """获取两个用户之间的关系兼容性分析"""
        if user_id1 not in self.user_profiles or user_id2 not in self.user_profiles:
            return {"compatibility_score": 0.0}
            
        # 计算相似度和互补性
        similarity = self.calculate_user_similarity(user_id1, user_id2)
        complementarity = self.calculate_complementarity(user_id1, user_id2)
        
        # 查找共同兴趣
        common_interests = self.find_common_interests(user_id1, user_id2)
        
        # 计算交互重叠度
        user1_items = set(self.user_item_interactions.get(user_id1, {}).keys())
        user2_items = set(self.user_item_interactions.get(user_id2, {}).keys())
        
        interaction_overlap = 0.0
        if user1_items and user2_items:
            common_items = user1_items.intersection(user2_items)
            all_items = user1_items.union(user2_items)
            
            if all_items:
                interaction_overlap = len(common_items) / len(all_items)
        
        # 综合兼容性得分
        compatibility_score = (
            similarity * 0.3 + 
            complementarity["complementarity_score"] * 0.4 + 
            (len(common_interests) / 10 if common_interests else 0) * 0.15 + 
            interaction_overlap * 0.15
        )
        
        # 兼容性分析结果
        compatibility_level = "高" if compatibility_score >= 0.7 else \
                              "中" if compatibility_score >= 0.4 else "低"
                              
        # 关系类型推断
        relationship_type = "朋友型" if similarity > complementarity["complementarity_score"] else \
                            "互补型" if complementarity["complementarity_score"] > similarity else \
                            "平衡型"
        
        # 获取用户性格特质数据（无需在此处添加，在API层处理）
        
        return {
            "compatibility_score": float(min(1.0, compatibility_score)),
            "similarity": float(similarity),
            "complementarity": complementarity,
            "common_interests_count": len(common_interests),
            "common_interests": common_interests,
            "interaction_overlap": float(interaction_overlap),
            "compatibility_level": compatibility_level,
            "relationship_type": relationship_type
        } 