<template>
  <div class="user-profile-page">
    <div class="container">
      <div class="page-header">
        <h1 class="page-title">个人资料</h1>
        <router-link to="/matches" class="btn btn-secondary">
          <i class="el-icon-back"></i> 查看匹配
        </router-link>
      </div>
      
      <div v-if="loading" class="loading-container">
        <el-skeleton style="width: 100%" animated>
          <template #template>
            <div style="padding: 20px;">
              <el-skeleton-item variant="image" style="width: 240px; height: 240px; margin-bottom: 20px;" />
              <el-skeleton-item variant="h1" style="width: 50%;" />
              <el-skeleton-item variant="text" style="margin-right: 16px; width: 30%;" />
              <el-skeleton-item variant="text" style="width: 100%;" />
              <el-skeleton-item variant="text" style="width: 100%;" />
            </div>
          </template>
        </el-skeleton>
      </div>
      
      <div v-else-if="error" class="error-alert">
        <el-alert :title="error" type="error" :closable="false"></el-alert>
      </div>
      
      <template v-else>
        <div class="profile-container">
          <!-- 个人信息卡片 -->
          <div class="profile-card card section">
            <div class="profile-header">
              <div class="user-avatar">
                <img :src="userData.avatar_url || '/src/assets/default-avatar.svg'" alt="用户头像" class="avatar-large">
                <el-button size="small" type="primary" plain class="upload-btn">
                  <i class="el-icon-upload"></i> 更新头像
                </el-button>
              </div>
              
              <div class="user-basic-info">
                <h2 class="user-name">{{ userData.name || `用户 ${userId}` }}</h2>
                <div class="user-meta">
                  <div v-if="userData.gender" class="meta-item">
                    <i class="el-icon-user"></i> {{ formatGender(userData.gender) }}
                  </div>
                  <div v-if="userData.age" class="meta-item">
                    <i class="el-icon-time"></i> {{ userData.age }}岁
                  </div>
                  <div v-if="userData.location" class="meta-item">
                    <i class="el-icon-location"></i> {{ userData.location }}
                  </div>
                </div>
                <div class="user-bio">{{ userData.bio || '这个用户很懒，还没有填写自我介绍...' }}</div>
              </div>
              
              <div class="action-buttons">
                <el-button type="primary" @click="isEditing = true">
                  <i class="el-icon-edit"></i> 编辑资料
                </el-button>
              </div>
            </div>
          </div>
          
          <!-- 性格特征可视化卡片 -->
          <div class="personality-card card section">
            <h3 class="section-title">性格特征分析</h3>
            <div class="personality-description">
              <p>基于您的行为和偏好，系统分析出您的性格特征如下（基于大五人格模型）：</p>
            </div>
            
            <div class="traits-container">
              <div class="radar-chart-container">
                <canvas ref="radarChart" width="300" height="300"></canvas>
              </div>
              
              <div class="traits-explained">
                <div v-for="(trait, key) in personalityTraits" :key="key" class="trait-item">
                  <div class="trait-header">
                    <div class="trait-name">{{ getTraitName(key) }}</div>
                    <div class="trait-score">
                      <el-progress 
                        :percentage="trait * 100" 
                        :color="getTraitColor(key, trait)"
                        :stroke-width="12"
                        :show-text="false"
                      ></el-progress>
                      <span class="score-value">{{ (trait * 100).toFixed(0) }}</span>
                    </div>
                  </div>
                  <div class="trait-description">{{ getTraitDescription(key, trait) }}</div>
                </div>
              </div>
            </div>
          </div>
          
          <!-- 兴趣爱好卡片 -->
          <div class="interests-card card section">
            <h3 class="section-title">兴趣爱好</h3>
            <div class="interests-container">
              <div v-if="userData.interests && userData.interests.length" class="interests-tags">
                <span v-for="(interest, idx) in userData.interests" :key="idx" class="interest-tag">
                  {{ interest }}
                </span>
              </div>
              <div v-else class="no-interests">
                还没有添加兴趣爱好，点击下方按钮添加
              </div>
              <div class="add-interest-btn">
                <el-button size="small" type="primary" plain @click="showAddInterestDialog">
                  <i class="el-icon-plus"></i> 添加兴趣
                </el-button>
              </div>
            </div>
          </div>
          
          <!-- 匹配偏好卡片 -->
          <div class="preferences-card card section">
            <h3 class="section-title">匹配偏好</h3>
            <div class="preferences-container">
              <el-form label-position="top">
                <el-form-item label="性别偏好">
                  <el-radio-group v-model="userData.preferences.gender_preference" disabled>
                    <el-radio label="male">男性</el-radio>
                    <el-radio label="female">女性</el-radio>
                    <el-radio label="both">不限</el-radio>
                  </el-radio-group>
                </el-form-item>
                
                <el-form-item label="年龄范围">
                  <el-slider
                    v-model="userData.preferences.age_range"
                    range
                    :min="18"
                    :max="80"
                    disabled
                  ></el-slider>
                  <div class="age-display">
                    {{ userData.preferences.age_range[0] }} - {{ userData.preferences.age_range[1] }} 岁
                  </div>
                </el-form-item>
                
                <el-form-item label="匹配偏好">
                  <div class="matching-preferences">
                    <div class="preference-item">
                      <span class="preference-label">相似度重要性：</span>
                      <el-rate
                        v-model="userData.preferences.similarity_importance"
                        disabled
                        :colors="['#99A9BF', '#F7BA2A', '#FF9900']"
                      ></el-rate>
                    </div>
                    
                    <div class="preference-item">
                      <span class="preference-label">互补性重要性：</span>
                      <el-rate
                        v-model="userData.preferences.complementarity_importance"
                        disabled
                        :colors="['#99A9BF', '#F7BA2A', '#FF9900']"
                      ></el-rate>
                    </div>
                  </div>
                </el-form-item>
              </el-form>
              
              <div class="preference-actions">
                <el-button type="primary" @click="showEditPreferencesDialog">
                  <i class="el-icon-setting"></i> 修改偏好设置
                </el-button>
              </div>
            </div>
          </div>
        </div>
        
        <!-- 编辑个人资料对话框 -->
        <el-dialog
          title="编辑个人资料"
          v-model="isEditing"
          width="500px"
        >
          <el-form :model="editForm" label-width="80px">
            <el-form-item label="昵称">
              <el-input v-model="editForm.name"></el-input>
            </el-form-item>
            <el-form-item label="性别">
              <el-select v-model="editForm.gender" placeholder="请选择">
                <el-option label="男" value="male"></el-option>
                <el-option label="女" value="female"></el-option>
                <el-option label="其他" value="other"></el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="年龄">
              <el-input-number v-model="editForm.age" :min="18" :max="100"></el-input-number>
            </el-form-item>
            <el-form-item label="所在地">
              <el-input v-model="editForm.location"></el-input>
            </el-form-item>
            <el-form-item label="自我介绍">
              <el-input type="textarea" v-model="editForm.bio" :rows="4"></el-input>
            </el-form-item>
          </el-form>
          <template #footer>
            <div class="dialog-footer">
              <el-button @click="isEditing = false">取消</el-button>
              <el-button type="primary" @click="saveProfile">保存</el-button>
            </div>
          </template>
        </el-dialog>
        
        <!-- 添加兴趣对话框 -->
        <el-dialog
          title="添加兴趣爱好"
          v-model="isAddingInterest"
          width="400px"
        >
          <el-form>
            <el-form-item>
              <el-select
                v-model="newInterests"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="请输入兴趣爱好"
              >
                <el-option
                  v-for="item in interestOptions"
                  :key="item"
                  :label="item"
                  :value="item"
                ></el-option>
              </el-select>
            </el-form-item>
          </el-form>
          <template #footer>
            <div class="dialog-footer">
              <el-button @click="isAddingInterest = false">取消</el-button>
              <el-button type="primary" @click="saveInterests">保存</el-button>
            </div>
          </template>
        </el-dialog>
        
        <!-- 编辑偏好设置对话框 -->
        <el-dialog
          title="编辑匹配偏好"
          v-model="isEditingPreferences"
          width="500px"
        >
          <el-form :model="preferenceForm" label-width="100px">
            <el-form-item label="性别偏好">
              <el-radio-group v-model="preferenceForm.gender_preference">
                <el-radio label="male">男性</el-radio>
                <el-radio label="female">女性</el-radio>
                <el-radio label="both">不限</el-radio>
              </el-radio-group>
            </el-form-item>
            
            <el-form-item label="年龄范围">
              <el-slider
                v-model="preferenceForm.age_range"
                range
                :min="18"
                :max="80"
              ></el-slider>
              <div class="age-display">
                {{ preferenceForm.age_range[0] }} - {{ preferenceForm.age_range[1] }} 岁
              </div>
            </el-form-item>
            
            <el-form-item label="相似度重要性">
              <el-rate
                v-model="preferenceForm.similarity_importance"
                :colors="['#99A9BF', '#F7BA2A', '#FF9900']"
              ></el-rate>
            </el-form-item>
            
            <el-form-item label="互补性重要性">
              <el-rate
                v-model="preferenceForm.complementarity_importance"
                :colors="['#99A9BF', '#F7BA2A', '#FF9900']"
              ></el-rate>
            </el-form-item>
          </el-form>
          <template #footer>
            <div class="dialog-footer">
              <el-button @click="isEditingPreferences = false">取消</el-button>
              <el-button type="primary" @click="savePreferences">保存</el-button>
            </div>
          </template>
        </el-dialog>
      </template>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue';
import { useRoute } from 'vue-router';
import { matchingService } from '../services/api';
import Chart from 'chart.js/auto';

export default {
  name: 'UserProfile',
  
  setup() {
    const route = useRoute();
    const userId = computed(() => route.params.userId || 'user_0001'); // 默认用户ID
    
    const loading = ref(true);
    const error = ref('');
    const userData = ref({
      user_id: 'user_0001',
      name: '示例用户',
      gender: 'male',
      age: 28,
      location: '北京',
      bio: '热爱生活，喜欢探索新事物。',
      avatar_url: null,
      interests: ['旅行', '摄影', '美食', '电影', '阅读'],
      preferences: {
        gender_preference: 'female',
        age_range: [24, 32],
        similarity_importance: 3,
        complementarity_importance: 4
      }
    });
    
    // 性格特征数据
    const personalityTraits = ref({
      extraversion: 0.75,
      agreeableness: 0.85,
      conscientiousness: 0.62,
      neuroticism: 0.30,
      openness: 0.90
    });
    
    // 编辑表单相关状态
    const isEditing = ref(false);
    const editForm = ref({});
    
    // 兴趣相关状态
    const isAddingInterest = ref(false);
    const newInterests = ref([]);
    const interestOptions = ref([
      '旅行', '摄影', '美食', '电影', '阅读', '音乐', '运动', '游泳',
      '健身', '瑜伽', '绘画', '手工', '编程', '游戏', '徒步', '烹饪',
      '写作', '舞蹈', '园艺', '冥想', '志愿服务'
    ]);
    
    // 偏好设置相关状态
    const isEditingPreferences = ref(false);
    const preferenceForm = ref({});
    
    // 雷达图引用
    const radarChart = ref(null);
    let chart = null;
    
    const fetchUserData = async () => {
      loading.value = true;
      error.value = '';
      
      try {
        // 模拟从API获取用户数据
        // const response = await userService.getUserProfile(userId.value);
        // userData.value = response.data;
        
        // 模拟延迟加载
        await new Promise(resolve => setTimeout(resolve, 800));
        
        // 模拟从API获取用户性格特征
        // const traitsResponse = await userService.getUserPersonalityTraits(userId.value);
        // personalityTraits.value = traitsResponse.data;
        
      } catch (err) {
        console.error('获取用户资料失败:', err);
        error.value = '获取用户资料失败，请稍后再试';
      } finally {
        loading.value = false;
      }
    };
    
    const formatGender = (gender) => {
      const genderMap = {
        'male': '男',
        'm': '男',
        '男': '男',
        'female': '女',
        'f': '女',
        '女': '女',
        'other': '其他'
      };
      return genderMap[gender.toLowerCase()] || '未知';
    };
    
    const initEditForm = () => {
      editForm.value = {
        name: userData.value.name,
        gender: userData.value.gender,
        age: userData.value.age,
        location: userData.value.location,
        bio: userData.value.bio
      };
    };
    
    const saveProfile = () => {
      // 模拟保存到API
      // await userService.updateUserProfile(userId.value, editForm.value);
      
      // 更新本地数据
      userData.value = {
        ...userData.value,
        ...editForm.value
      };
      
      isEditing.value = false;
      
      // 显示成功提示
      ElMessage({
        message: '个人资料更新成功',
        type: 'success'
      });
    };
    
    const showAddInterestDialog = () => {
      newInterests.value = [...userData.value.interests];
      isAddingInterest.value = true;
    };
    
    const saveInterests = () => {
      // 模拟保存到API
      // await userService.updateUserInterests(userId.value, newInterests.value);
      
      // 更新本地数据
      userData.value.interests = [...newInterests.value];
      isAddingInterest.value = false;
      
      // 显示成功提示
      ElMessage({
        message: '兴趣爱好更新成功',
        type: 'success'
      });
    };
    
    const showEditPreferencesDialog = () => {
      preferenceForm.value = { ...userData.value.preferences };
      isEditingPreferences.value = true;
    };
    
    const savePreferences = () => {
      // 模拟保存到API
      // await userService.updateUserPreferences(userId.value, preferenceForm.value);
      
      // 更新本地数据
      userData.value.preferences = { ...preferenceForm.value };
      isEditingPreferences.value = false;
      
      // 显示成功提示
      ElMessage({
        message: '匹配偏好更新成功',
        type: 'success'
      });
    };
    
    const initRadarChart = () => {
      if (!radarChart.value) return;
      
      // 如果已存在图表，销毁它
      if (chart) {
        chart.destroy();
      }
      
      // 创建雷达图
      const ctx = radarChart.value.getContext('2d');
      chart = new Chart(ctx, {
        type: 'radar',
        data: {
          labels: [
            '外向性',
            '宜人性',
            '尽责性',
            '神经质性',
            '开放性'
          ],
          datasets: [{
            label: '性格特征',
            data: [
              personalityTraits.value.extraversion * 100,
              personalityTraits.value.agreeableness * 100,
              personalityTraits.value.conscientiousness * 100,
              personalityTraits.value.neuroticism * 100,
              personalityTraits.value.openness * 100
            ],
            fill: true,
            backgroundColor: 'rgba(54, 162, 235, 0.2)',
            borderColor: 'rgb(54, 162, 235)',
            pointBackgroundColor: 'rgb(54, 162, 235)',
            pointBorderColor: '#fff',
            pointHoverBackgroundColor: '#fff',
            pointHoverBorderColor: 'rgb(54, 162, 235)'
          }]
        },
        options: {
          scales: {
            r: {
              min: 0,
              max: 100,
              ticks: {
                stepSize: 20
              }
            }
          }
        }
      });
    };
    
    const getTraitName = (key) => {
      const traitNames = {
        'extraversion': '外向性',
        'agreeableness': '宜人性',
        'conscientiousness': '尽责性',
        'neuroticism': '神经质性',
        'openness': '开放性'
      };
      return traitNames[key] || key;
    };
    
    const getTraitDescription = (key, value) => {
      // 根据特征和值返回描述
      if (key === 'extraversion') {
        if (value >= 0.7) return '您是一个外向、热情、善于社交的人。喜欢与人交流，充满活力。';
        if (value >= 0.4) return '您既能享受社交活动，也能适应独处时光。平衡内外向特质。';
        return '您更倾向于安静、独处和深度思考。社交活动会消耗您的能量。';
      }
      if (key === 'agreeableness') {
        if (value >= 0.7) return '您非常友善、富有同情心且乐于助人。重视和谐关系和他人感受。';
        if (value >= 0.4) return '您能在合作与竞争之间取得平衡，既有同理心也有独立思考。';
        return '您思考方式独立、直接，更看重真实表达而非迎合他人。';
      }
      if (key === 'conscientiousness') {
        if (value >= 0.7) return '您做事有条理、负责任且可靠。注重计划和细节，追求目标坚定。';
        if (value >= 0.4) return '您兼顾计划性和灵活性，既能遵循规则也能适时调整。';
        return '您更注重当下体验，灵活多变，不拘泥于严格计划或规则。';
      }
      if (key === 'neuroticism') {
        if (value >= 0.7) return '您情绪波动较大，对压力较为敏感。可能更容易感到焦虑和担忧。';
        if (value >= 0.4) return '您对压力反应适中，情绪状态相对平稳，偶尔会有波动。';
        return '您情绪稳定，抗压能力强，面对挫折能保持积极乐观的态度。';
      }
      if (key === 'openness') {
        if (value >= 0.7) return '您好奇心强，富有想象力，喜欢尝试新事物和创新思考。';
        if (value >= 0.4) return '您平衡传统与创新，既尊重经验也愿意适度探索新领域。';
        return '您偏爱熟悉和实际的事物，注重现实和传统，追求稳定性。';
      }
      return '暂无描述';
    };
    
    const getTraitColor = (key, value) => {
      // 对于神经质性，分数越低越好
      if (key === 'neuroticism') {
        if (value <= 0.3) return '#38b000'; // 低神经质是好的，绿色
        if (value <= 0.6) return '#ffb703'; // 中等神经质是中性的，黄色
        return '#d62828'; // 高神经质是挑战，红色
      }
      
      // 对于其他特质，分数越高越好
      if (value >= 0.7) return '#38b000'; // 高分，绿色
      if (value >= 0.4) return '#ffb703'; // 中等分，黄色
      return '#d62828'; // 低分，红色
    };
    
    onMounted(() => {
      fetchUserData();
      initEditForm();
      
      // 在数据加载完成后初始化雷达图
      setTimeout(() => {
        initRadarChart();
      }, 1000);
    });
    
    return {
      userId,
      loading,
      error,
      userData,
      personalityTraits,
      isEditing,
      editForm,
      isAddingInterest,
      newInterests,
      interestOptions,
      isEditingPreferences,
      preferenceForm,
      radarChart,
      
      formatGender,
      initEditForm,
      saveProfile,
      showAddInterestDialog,
      saveInterests,
      showEditPreferencesDialog,
      savePreferences,
      getTraitName,
      getTraitDescription,
      getTraitColor
    };
  }
};
</script>

<style scoped>
.user-profile-page {
  padding: 20px 0;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 28px;
  color: #333;
  margin: 0;
}

.card {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  margin-bottom: 24px;
  overflow: hidden;
}

.section {
  padding: 24px;
}

.section-title {
  font-size: 20px;
  color: #333;
  margin-top: 0;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 1px solid #eee;
}

.profile-header {
  display: flex;
  flex-wrap: wrap;
}

.user-avatar {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-right: 24px;
}

.avatar-large {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  object-fit: cover;
  margin-bottom: 12px;
  background-color: #f0f0f0;
}

.user-basic-info {
  flex: 1;
}

.user-name {
  font-size: 24px;
  margin: 0 0 12px;
}

.user-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 12px;
  color: #666;
}

.meta-item {
  display: flex;
  align-items: center;
}

.meta-item i {
  margin-right: 6px;
}

.user-bio {
  color: #666;
  white-space: pre-line;
}

.action-buttons {
  margin-left: auto;
  align-self: flex-start;
}

.personality-description {
  margin-bottom: 20px;
  color: #666;
}

.traits-container {
  display: flex;
  flex-wrap: wrap;
}

.radar-chart-container {
  width: 300px;
  height: 300px;
  margin-right: 24px;
}

.traits-explained {
  flex: 1;
}

.trait-item {
  margin-bottom: 16px;
}

.trait-header {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.trait-name {
  width: 100px;
  font-weight: bold;
}

.trait-score {
  flex: 1;
  display: flex;
  align-items: center;
}

.score-value {
  margin-left: 8px;
  font-weight: bold;
}

.trait-description {
  color: #666;
  font-size: 14px;
  padding-left: 100px;
}

.interests-container {
  padding: 10px 0;
}

.interests-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.interest-tag {
  background-color: #f0f4ff;
  color: #3d7eff;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 14px;
}

.no-interests {
  color: #999;
  margin-bottom: 16px;
}

.add-interest-btn {
  margin-top: 10px;
}

.preferences-container {
  max-width: 600px;
}

.age-display {
  color: #666;
  text-align: center;
  margin-top: 5px;
}

.matching-preferences {
  margin-top: 10px;
}

.preference-item {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
}

.preference-label {
  width: 150px;
}

.preference-actions {
  margin-top: 20px;
}

@media (max-width: 768px) {
  .profile-header {
    flex-direction: column;
  }
  
  .user-avatar {
    margin-right: 0;
    margin-bottom: 20px;
  }
  
  .action-buttons {
    margin-left: 0;
    margin-top: 20px;
    align-self: auto;
  }
  
  .traits-container {
    flex-direction: column;
  }
  
  .radar-chart-container {
    margin-right: 0;
    margin-bottom: 24px;
    width: 100%;
  }
  
  .trait-description {
    padding-left: 0;
  }
}
</style> 