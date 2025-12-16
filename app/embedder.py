from sentence_transformers import SentenceTransformer
import numpy as np

#to load a lightweight multilingual model
model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

def get_vector(text):
    """
    输入文本，输出 384 维度的向量 (list of floats)
    """
    embedding = model.encode(text)
    return embedding.tolist()

# test
if __name__ == "__main__":
    vec = get_vector("周五去健身房")
    print(f"向量维度: {len(vec)}")
    print(f"前5位数据: {vec[:5]}")