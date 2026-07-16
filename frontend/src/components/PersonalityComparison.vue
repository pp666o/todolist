<template>
  <div class="personality-comparison">
    <h3 class="section-title">性格特质比较</h3>
    
    <div v-if="loading" class="loading-container">
      <el-skeleton animated :rows="5"></el-skeleton>
    </div>
    
    <div v-else-if="error" class="error-alert">
      <el-alert :title="error" type="error" :closable="false"></el-alert>
    </div>
    
    <div v-else-if="traits1 && traits2" class="traits-container">
      <!-- 性格雷达图 -->
      <div class="radar-chart-container">
        <canvas ref="radarChart"></canvas>
      </div>
      
      <!-- 性格特质列表 -->
      <div class="traits-comparison">
        <div class="traits-header">
          <div class="trait-label">性格特质</div>
          <div class="user1-label">{{ user1Name }}</div>
          <div class="user2-label">{{ user2Name }}</div>
          <div class="compatibility-label">兼容度</div>
        </div>
        
        <div v-for="(trait, index) in traitLabels" :key="index" class="trait-row">
          <div class="trait-label">{{ getTraitLabel(trait) }}</div>
          <div class="user1-value">
            <el-progress :percentage="getTraitPercentage(traits1[trait])" 
                       :color="getTraitColor(trait)" :show-text="false"></el-progress>
            <span class="trait-score">{{ getTraitScore(traits1[trait]) }}</span>
          </div>
          <div class="user2-value">
            <el-progress :percentage="getTraitPercentage(traits2[trait])" 
                       :color="getTraitColor(trait)" :show-text="false"></el-progress>
            <span class="trait-score">{{ getTraitScore(traits2[trait]) }}</span>
          </div>
          <div class="compatibility-value">
            <span :class="getCompatibilityClass(getTraitCompatibility(trait))">
              {{ getTraitCompatibility(trait) }}
            </span>
          </div>
        </div>
      </div>
      
      <!-- 性格兼容性说明 -->
      <div class="compatibility-explanation">
        <h4>性格兼容性分析</h4>
        <p>{{ compatibilityExplanation }}</p>
        <div class="compatibility-tips">
          <div class="tip-strength" v-if="strengths.length > 0">
            <h5><i class="el-icon-star-on"></i> 关系优势</h5>
            <ul>
              <li v-for="(strength, index) in strengths" :key="'s-'+index">{{ strength }}</li>
            </ul>
          </div>
          <div class="tip-challenge" v-if="challenges.length > 0">
            <h5><i class="el-icon-warning-outline"></i> 潜在挑战</h5>
            <ul>
              <li v-for="(challenge, index) in challenges" :key="'c-'+index">{{ challenge }}</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
    
    <div v-else class="no-data">
      <p>无法获取用户性格数据</p>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed, watch } from 'vue'
import { matchingService } from '../services/api'
import Chart from 'chart.js/auto'

export default {
  name: 'PersonalityComparison',
  props: {
    userId1: {
      type: String,
      required: true
    },
    userId2: {
      type: String,
      required: true
    },
    user1Name: {
      type: String,
      default: '用户1'
    },
    user2Name: {
      type: String,
      default: '用户2'
    }
  },
  setup(props) {
    const loading = ref(true)
    const error = ref('')
    const traits1 = ref(null)
    const traits2 = ref(null)
    const compatibilityScore = ref(0)
    const radarChart = ref(null)
    const chartInstance = ref(null)
    
    const traitLabels = ['extraversion', 'agreeableness', 'conscientiousness', 'neuroticism', 'openness']
    
    const getTraitLabel = (trait) => {
      const labels = {
        'extraversion': '外向性',
        'agreeableness': '宜人性',
        'conscientiousness': '尽责性',
        'neuroticism': '神经质',
        'openness': '开放性'
      }
      return labels[trait] || trait
    }
    
    const getTraitDescription = (trait) => {
      const descriptions = {
        'extraversion': '表示社交能力、活跃程度和积极情感的倾向',
        'agreeableness': '表示合作、同情和温暖的倾向',
        'conscientiousness': '表示组织性、可靠性和负责任的倾向',
        'neuroticism': '表示负面情绪和情绪不稳定的倾向',
        'openness': '表示好奇心、创造力和对新体验的接受度'
      }
      return descriptions[trait] || ''
    }
    
    const getTraitPercentage = (value) => {
      return value ? Math.round(value * 100) : 0
    }
    
    const getTraitScore = (value) => {
      return value ? (value * 10).toFixed(1) : '0.0'
    }
    
    const getTraitColor = (trait) => {
      const colors = {
        'extraversion': '#3498db',
        'agreeableness': '#2ecc71',
        'conscientiousness': '#9b59b6',
        'neuroticism': '#e74c3c',
        'openness': '#f39c12'
      }
      return colors[trait] || '#3498db'
    }
    
    const getTraitCompatibility = (trait) => {
      if (!traits1.value || !traits2.value) return '未知'
      
      // 根据性格特质计算兼容性
      // 相似性维度: 开放性、宜人性、尽责性
      if (['openness', 'agreeableness', 'conscientiousness'].includes(trait)) {
        // 相似越好
        const similarity = 1.0 - Math.abs(traits1.value[trait] - traits2.value[trait])
        if (similarity >= 0.8) return '极佳'
        if (similarity >= 0.6) return '优秀'
        if (similarity >= 0.4) return '一般'
        return '较低'
      }
      
      // 互补性维度: 外向性
      if (trait === 'extraversion') {
        // 一个高一个低较好
        const diff = Math.abs(traits1.value[trait] - traits2.value[trait])
        // 互补性最佳在差异0.4-0.6之间
        const complementarity = 1.0 - Math.abs(diff - 0.5) * 2
        if (complementarity >= 0.8) return '极佳'
        if (complementarity >= 0.6) return '优秀'
        if (complementarity >= 0.4) return '一般'
        return '较低'
      }
      
      // 低分较好维度: 神经质
      if (trait === 'neuroticism') {
        // 都低比较好
        const avgScore = (traits1.value[trait] + traits2.value[trait]) / 2.0
        const lowScoreBenefit = 1.0 - avgScore
        if (lowScoreBenefit >= 0.8) return '极佳'
        if (lowScoreBenefit >= 0.6) return '优秀'
        if (lowScoreBenefit >= 0.4) return '一般'
        return '较低'
      }
      
      return '未知'
    }
    
    const getCompatibilityClass = (level) => {
      const classMap = {
        '极佳': 'compatibility-excellent',
        '优秀': 'compatibility-good',
        '一般': 'compatibility-fair',
        '较低': 'compatibility-poor',
        '未知': 'compatibility-unknown'
      }
      return classMap[level] || 'compatibility-unknown'
    }
    
    const compatibilityExplanation = computed(() => {
      if (!traits1.value || !traits2.value) return ''
      
      const explanations = []
      let overallScore = 0
      
      // 评估每个维度并累计总分
      for (const trait of traitLabels) {
        let score = 0
        let explanation = ''
        
        // 相似性维度: 开放性、宜人性、尽责性
        if (['openness', 'agreeableness', 'conscientiousness'].includes(trait)) {
          const similarity = 1.0 - Math.abs(traits1.value[trait] - traits2.value[trait])
          score = similarity
          
          if (similarity >= 0.7) {
            explanation = `你们在${getTraitLabel(trait)}上非常相似，这有助于相互理解和共鸣。`
          } else if (similarity <= 0.3) {
            explanation = `你们在${getTraitLabel(trait)}上差异较大，可能需要更多沟通来理解彼此的思维方式。`
          }
        }
        
        // 互补性维度: 外向性
        if (trait === 'extraversion') {
          const diff = Math.abs(traits1.value[trait] - traits2.value[trait])
          const complementarity = 1.0 - Math.abs(diff - 0.5) * 2
          score = complementarity
          
          if (complementarity >= 0.7) {
            explanation = `你们在外向性上形成很好的互补，一个可能更健谈，一个可能更善于倾听。`
          } else if (traits1.value[trait] >= 0.7 && traits2.value[trait] >= 0.7) {
            explanation = `你们都很外向，可能会共同享受社交活动，但可能需要注意倾听对方的需求。`
          } else if (traits1.value[trait] <= 0.3 && traits2.value[trait] <= 0.3) {
            explanation = `你们都比较内向，可能会共同享受安静的活动，但可能需要有人主动打破沉默。`
          }
        }
        
        // 低分较好维度: 神经质
        if (trait === 'neuroticism') {
          const avgScore = (traits1.value[trait] + traits2.value[trait]) / 2.0
          const lowScoreBenefit = 1.0 - avgScore
          score = lowScoreBenefit
          
          if (lowScoreBenefit >= 0.7) {
            explanation = `你们的情绪都比较稳定，有助于建立平和、积极的关系。`
          } else if (lowScoreBenefit <= 0.3) {
            explanation = `你们可能都有些情绪波动，建议学习一些情绪管理技巧来增强关系稳定性。`
          }
        }
        
        if (explanation) {
          explanations.push(explanation)
        }
        overallScore += score
      }
      
      // 计算平均分数并设置总体评价
      compatibilityScore.value = overallScore / traitLabels.length
      
      let overallEvaluation = ''
      if (compatibilityScore.value >= 0.7) {
        overallEvaluation = '总体来看，你们的性格特质非常匹配，有很高的兼容性。'
      } else if (compatibilityScore.value >= 0.5) {
        overallEvaluation = '总体来看，你们的性格特质较为匹配，关系有良好的发展潜力。'
      } else if (compatibilityScore.value >= 0.3) {
        overallEvaluation = '总体来看，你们的性格特质有一定差异，但通过沟通和理解仍能建立良好关系。'
      } else {
        overallEvaluation = '总体来看，你们的性格特质差异较大，可能需要更多的包容和理解。'
      }
      
      // 随机选择2-3条具体解释加入总体评价
      const selectedExplanations = explanations.sort(() => 0.5 - Math.random()).slice(0, Math.min(3, explanations.length))
      
      return [overallEvaluation, ...selectedExplanations].join(' ')
    })
    
    const strengths = computed(() => {
      if (!traits1.value || !traits2.value) return []
      
      const results = []
      
      // 外向性互补
      const extraDiff = Math.abs(traits1.value.extraversion - traits2.value.extraversion)
      if (extraDiff >= 0.4) {
        results.push('你们在社交能力上互补，一方可能更擅长社交场合，另一方可能更善于深度交流。')
      }
      
      // 开放性高
      const avgOpenness = (traits1.value.openness + traits2.value.openness) / 2
      if (avgOpenness >= 0.6) {
        results.push('你们都有较高的开放性，会愿意尝试新事物，共同成长。')
      }
      
      // 宜人性高
      const avgAgreeableness = (traits1.value.agreeableness + traits2.value.agreeableness) / 2
      if (avgAgreeableness >= 0.6) {
        results.push('你们都比较宜人，善于理解和关心对方，有助于建立和谐关系。')
      }
      
      // 尽责性相似且高
      const consSimilarity = 1.0 - Math.abs(traits1.value.conscientiousness - traits2.value.conscientiousness)
      const avgCons = (traits1.value.conscientiousness + traits2.value.conscientiousness) / 2
      if (consSimilarity >= 0.7 && avgCons >= 0.6) {
        results.push('你们在责任感和组织能力上十分相似，可以共同规划和完成目标。')
      }
      
      // 神经质都低
      const avgNeuroticism = (traits1.value.neuroticism + traits2.value.neuroticism) / 2
      if (avgNeuroticism <= 0.4) {
        results.push('你们的情绪都比较稳定，不易受小事困扰，有助于建立平稳的关系。')
      }
      
      return results.slice(0, 3) // 最多返回3条
    })
    
    const challenges = computed(() => {
      if (!traits1.value || !traits2.value) return []
      
      const results = []
      
      // 外向性都高或都低
      const extraSimilarity = 1.0 - Math.abs(traits1.value.extraversion - traits2.value.extraversion)
      const avgExtra = (traits1.value.extraversion + traits2.value.extraversion) / 2
      if (extraSimilarity >= 0.7) {
        if (avgExtra >= 0.7) {
          results.push('你们都很外向，可能会争夺社交场合的注意力，建议给对方表达的空间。')
        } else if (avgExtra <= 0.3) {
          results.push('你们都较为内向，可能需要有人主动破冰，否则关系可能发展缓慢。')
        }
      }
      
      // 开放性差异大
      const openSimilarity = 1.0 - Math.abs(traits1.value.openness - traits2.value.openness)
      if (openSimilarity <= 0.4) {
        results.push('你们在开放性上差异较大，一方可能更喜欢尝试新事物，另一方可能偏好熟悉的环境，需要在活动选择上寻找平衡。')
      }
      
      // 尽责性差异大
      const consSimilarity = 1.0 - Math.abs(traits1.value.conscientiousness - traits2.value.conscientiousness)
      if (consSimilarity <= 0.4) {
        results.push('你们在责任感和组织能力上差异较大，可能对计划和执行有不同期望，建议明确分工和责任。')
      }
      
      // 神经质都高
      const avgNeuroticism = (traits1.value.neuroticism + traits2.value.neuroticism) / 2
      if (avgNeuroticism >= 0.6) {
        results.push('你们的情绪可能都有些波动，建议学习情绪管理技巧，避免在压力下相互影响。')
      }
      
      // 宜人性差异大
      const agreeSimilarity = 1.0 - Math.abs(traits1.value.agreeableness - traits2.value.agreeableness)
      if (agreeSimilarity <= 0.4) {
        results.push('你们在宜人性上差异较大，一方可能更愿意妥协，另一方可能更直接，需要在沟通方式上相互适应。')
      }
      
      return results.slice(0, 3) // 最多返回3条
    })
    
    const fetchPersonalityData = async () => {
      loading.value = true
      error.value = ''
      
      try {
        // 获取关系兼容性数据，其中包含性格特质
        const response = await matchingService.getRelationshipCompatibility(props.userId1, props.userId2)
        const compatibility = response.data.compatibility
        
        // 从兼容性数据中提取性格特质
        if (compatibility && compatibility.personality_traits) {
          traits1.value = compatibility.personality_traits.user1 || null
          traits2.value = compatibility.personality_traits.user2 || null
          
          // 如果成功获取了性格特质，绘制雷达图
          if (traits1.value && traits2.value) {
            renderRadarChart()
          }
        }
      } catch (err) {
        console.error('获取性格特质数据失败:', err)
        error.value = '无法获取性格特质数据，请稍后再试'
      } finally {
        loading.value = false
      }
    }
    
    const renderRadarChart = () => {
      if (!traits1.value || !traits2.value || !radarChart.value) return
      
      const ctx = radarChart.value.getContext('2d')
      
      // 销毁之前的图表实例
      if (chartInstance.value) {
        chartInstance.value.destroy()
      }
      
      // 准备数据
      const labels = traitLabels.map(getTraitLabel)
      const data1 = traitLabels.map(trait => traits1.value[trait] || 0)
      const data2 = traitLabels.map(trait => traits2.value[trait] || 0)
      
      // 创建新的图表实例
      chartInstance.value = new Chart(ctx, {
        type: 'radar',
        data: {
          labels: labels,
          datasets: [
            {
              label: props.user1Name,
              data: data1,
              backgroundColor: 'rgba(54, 162, 235, 0.2)',
              borderColor: 'rgb(54, 162, 235)',
              pointBackgroundColor: 'rgb(54, 162, 235)',
              pointBorderColor: '#fff',
              pointHoverBackgroundColor: '#fff',
              pointHoverBorderColor: 'rgb(54, 162, 235)'
            },
            {
              label: props.user2Name,
              data: data2,
              backgroundColor: 'rgba(255, 99, 132, 0.2)',
              borderColor: 'rgb(255, 99, 132)',
              pointBackgroundColor: 'rgb(255, 99, 132)',
              pointBorderColor: '#fff',
              pointHoverBackgroundColor: '#fff',
              pointHoverBorderColor: 'rgb(255, 99, 132)'
            }
          ]
        },
        options: {
          scales: {
            r: {
              angleLines: {
                display: true
              },
              suggestedMin: 0,
              suggestedMax: 1
            }
          }
        }
      })
    }
    
    // 监听属性变化，重新获取数据
    watch([() => props.userId1, () => props.userId2], () => {
      fetchPersonalityData()
    })
    
    onMounted(() => {
      fetchPersonalityData()
    })
    
    return {
      loading,
      error,
      traits1,
      traits2,
      traitLabels,
      radarChart,
      compatibilityExplanation,
      strengths,
      challenges,
      getTraitLabel,
      getTraitPercentage,
      getTraitScore,
      getTraitColor,
      getTraitCompatibility,
      getCompatibilityClass
    }
  }
}
</script>

<style scoped>
.personality-comparison {
  margin: 2rem 0;
}

.section-title {
  font-size: 1.5rem;
  color: var(--primary-color);
  margin-bottom: 1.5rem;
}

.loading-container {
  margin-bottom: 2rem;
}

.error-alert {
  margin-bottom: 2rem;
}

.traits-container {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.radar-chart-container {
  width: 100%;
  max-width: 500px;
  margin: 0 auto;
  height: 300px;
}

.traits-comparison {
  border: 1px solid #eaeaea;
  border-radius: 8px;
  overflow: hidden;
}

.traits-header {
  display: grid;
  grid-template-columns: 1.5fr 2fr 2fr 1fr;
  background-color: #f6f6f6;
  padding: 12px 16px;
  font-weight: bold;
}

.trait-row {
  display: grid;
  grid-template-columns: 1.5fr 2fr 2fr 1fr;
  padding: 16px;
  border-top: 1px solid #eaeaea;
  align-items: center;
}

.trait-label {
  font-weight: 500;
}

.user1-value,
.user2-value {
  display: flex;
  align-items: center;
}

.user1-value .el-progress,
.user2-value .el-progress {
  margin-right: 10px;
  width: 70%;
}

.trait-score {
  font-weight: 600;
  min-width: 30px;
}

.compatibility-value {
  font-weight: 600;
  text-align: center;
}

.compatibility-excellent {
  color: #38b000;
}

.compatibility-good {
  color: #84cc16;
}

.compatibility-fair {
  color: #fb8500;
}

.compatibility-poor {
  color: #ef4444;
}

.compatibility-unknown {
  color: #9ca3af;
}

.compatibility-explanation {
  background-color: #f8f9fa;
  border-radius: 8px;
  padding: 1.5rem;
}

.compatibility-explanation h4 {
  margin-top: 0;
  margin-bottom: 1rem;
  font-size: 1.1rem;
}

.compatibility-explanation p {
  margin-bottom: 1.5rem;
}

.compatibility-tips {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
}

.tip-strength h5,
.tip-challenge h5 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 0;
  margin-bottom: 0.5rem;
}

.tip-strength h5 {
  color: #38b000;
}

.tip-challenge h5 {
  color: #fb8500;
}

.tip-strength ul,
.tip-challenge ul {
  margin: 0;
  padding-left: 1.5rem;
}

.tip-strength li,
.tip-challenge li {
  margin-bottom: 0.5rem;
}

.no-data {
  text-align: center;
  padding: 2rem;
  color: #666;
}

@media (max-width: 768px) {
  .compatibility-tips {
    grid-template-columns: 1fr;
  }
  
  .traits-header,
  .trait-row {
    grid-template-columns: 1.5fr 1.2fr 1.2fr 1fr;
  }
  
  .user1-value .el-progress,
  .user2-value .el-progress {
    width: 60%;
  }
}
</style> 