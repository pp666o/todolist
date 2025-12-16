from sentence_transformers import SentenceTransformer
import os

print(">>> [AI Model] 正在加载语义模型 (首次运行会自动下载 ~400MB)...")

#paraphrase-multilingual-MiniLM-L12-v2 支持中文且维度为 384
model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

print(">>> [AI Model] 模型加载完毕！")

def get_embedding(text: str) -> list[float]:
    """
    输入文本，输出 384 维的高维语义向量。
    """
    if not text:
        return [0.0] * 384
    
    #model.encode 返回的是 numpy array，需要转为 list 存入数据库
    embedding = model.encode(text)
    
    return embedding.tolist()