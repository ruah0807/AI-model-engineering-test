from fastapi import FastAPI, HTTPException,Query
from typing import List, Dict

from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from recipies import RecipeCrawler
from vector.recipe2vec import recipe_to_vector,some_embedding_function
from vector.food2vec_embedding import recipe_to_vector_food2vec, some_embedding_function_food2vec


# env 관련
from dotenv import load_dotenv
import os

# db예제
from pymongo.errors import BulkWriteError, ServerSelectionTimeoutError
from pymongo.mongo_client import MongoClient
from pymongo import UpdateOne

from pinecone import Pinecone
import json



# .env 파일의 변수를 프로그램 환경변수에 추가
load_dotenv()

DB_ID = os.getenv('DB_ID')
DB_PW = os.getenv('DB_PW')
DB_URL = os.getenv('DB_URL')
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')

app = FastAPI()

# MongoDB client 생성
uri = f'mongodb+srv://{DB_ID}:{DB_PW}{DB_URL}'
client = MongoClient(uri)
db = client.crawling_test

try:
    # MongoDB 클라이언트 생성
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    # 연결 테스트
    client.server_info()
    print("MongoDB 연결 성공")
except ServerSelectionTimeoutError as err:
    print(f"MongoDB 연결 실패: {err}")
    
# Pinecone 초기화
pc = Pinecone(api_key=PINECONE_API_KEY)

index_name = 'recipes'
# if index_name not in pc.list_indexes().names():
#     pc.create_index(
#         name=index_name, 
#         dimension=384,  #384 차원 백터 사용
#         metric='cosine',
#         spec=ServerlessSpec(
#             cloud='aws',
#             region='us-east-1'
#         )
    # )
index = pc.Index(index_name)



def recipes_serializer(recipe) -> dict:
    return {
        "id" : str(recipe["_id"]),
        "recipe_id": recipe["recipe_id"] if recipe.get('recipe_id') else '',
        "title": recipe["title"] if recipe.get('title') else '',
        "oriUrl": recipe["oriUrl"] if recipe.get('oriUrl') else '',
        "level": recipe["level"] if recipe.get('level') else '',
        "serving": recipe["serving"] if recipe.get('serving') else '',
        "cookingTime": recipe["cookingTime"] if recipe.get('cookingTime') else '',
        "ingredients": recipe["ingredients"] if recipe.get('ingredients') else '',
        "instructions": recipe["instructions"] if recipe.get('instructions') else '',
        "tools": recipe["tools"] if recipe.get('tools') else '',
        "platform": recipe["platform"] if recipe.get('platform') else '',
        "publishDate": recipe["publishDate"] if recipe.get('publishDate') else '',
        "createdDate": recipe["createdDate"] if recipe.get('createdDate') else '',
        "imgUrl": recipe["imgUrl"] if recipe.get('imgUrl') else ''  
    }


## 페이지별 크롤링 확인 GET ##
@app.get("/ddook_recipes/{recipe_id}", response_model=Dict)
def get_detail_by_recipe_id(recipe_id:str):
    recipe = db.recipes.find_one({'recipe_id': recipe_id})
    if recipe : 
        return recipes_serializer(recipe)
    else:
        raise  HTTPException(status_code=404, detail='해당 번호의 뚝딱이형 레시피없음')




### 전체 크롤링 디비 저장 ###
@app.post("/ddook_recipes/save_all", response_model=List[Dict])
def save_recipes():
    base_url = 'https://chef-choice.tistory.com'
    crawler = RecipeCrawler(base_url)
    all_recipes_data = crawler.all_crawling()
    
    operations = [ 
                  UpdateOne({'recipe_id':recipe['recipe_id']}, {'$set': recipe}, upsert=True)
                  for recipe in all_recipes_data
                  ]
    
    if operations :
        try:
            db.recipes.bulk_write(operations)
        except BulkWriteError as bwe:
            raise HTTPException(status_code=500, detail=f'중복 레시피 에러 : {bwe.details}')
        
        
    # 저장된 레시피들만 반환
    saved_recipes_ids = [recipe['recipe_id'] for recipe in all_recipes_data]
    saved_recipes =  db.recipes.find({'recipe_id' : {'$in': saved_recipes_ids}})
        
    return [recipes_serializer(recipe) for recipe in saved_recipes]
    
    



### 페이지별 크롤링 저장 ###
@app.post("/ddook_recipes/save", response_model=List[Dict])
def save_recipes(page_num : int = Query(1, description="Page number to crawl recipes from")):
    base_url = 'https://chef-choice.tistory.com'
    crawler = RecipeCrawler(base_url)
    all_recipes_data = crawler.page_crawling(page_num)
    
    operations = [ 
                  UpdateOne({'recipe_id':recipe['recipe_id']}, {'$set': recipe}, upsert=True)
                  for recipe in all_recipes_data
                  ]
    
    if operations :
        try:
            db.recipes.bulk_write(operations)
        except BulkWriteError as bwe:
            raise HTTPException(status_code=500, detail=f'중복 레시피 에러 : {bwe.details}')
        
        
    # 저장된 레시피들만 반환
    saved_recipes_ids = [recipe['recipe_id'] for recipe in all_recipes_data]
    saved_recipes =  db.recipes.find({'recipe_id' : {'$in': saved_recipes_ids}})
        
    return [recipes_serializer(recipe) for recipe in saved_recipes]



### 몽고DB에 저장된 데이터 파인콘에 백터화한 후 저장 ###
@app.post('/ddook_recipes/index_to_pinecone', response_model=Dict)
def index_to_pinecone():
    
    recipes=db.recipes.find()
    vectors =[]
    
    for recipe in recipes :
        vector = {
            'id': recipe['recipe_id'],
            'values' : recipe_to_vector(recipe) ,
            'metadata': {
                'title':recipe['title'],
                'author':recipe['author'],
                # json 변환된 ingredients 필드
                'ingredients' :json.dumps(recipe['ingredients'], ensure_ascii=False),
                'instructions': recipe['instructions']
            }
        }
        vectors.append(vector)
        
    index.upsert(vectors=vectors)
    return {'status':'success', 'indexed': len(vectors)}

### food2vec을 이용한 재료 저장 ###
@app.post('/ddook_recipes/food2vec', response_model=Dict)
def index_to_pinecone():
    
    recipes=db.recipes.find()
    vectors =[]
    
    for recipe in recipes :
        vector = {
            'id': recipe['recipe_id'],
            'values' : recipe_to_vector_food2vec(recipe) ,
            'metadata': {
                'title':recipe['title'],
                'author':recipe['author'],
                'publishAt': recipe['publishAt']
            }
        }
        vectors.append(vector)
        
    index.upsert(vectors=vectors)
    return {'status':'success', 'indexed': len(vectors)}
    


### 하이브리드 검색 : MongoDB + Pinecone 정확도와 유사도 검색 ###

# @app.get("/hybrid_search", response_model=List[Dict])
# def hybrid_search(query: str):
#     # Pinecone에서 검색
#     vector_query = some_embedding_function(query)
#     pinecone_results = index.query(vector=vector_query, top_k=10, include_values=False, include_metadata=True)

#     print(f"Pinecone Results: {pinecone_results}")


#     # Pinecone 검색 결과에서 레시피 ID 추출 및 유사도 점수 저장
#     pinecone_data = {result['id']: result['score'] for result in pinecone_results['matches']}
    
#     # MongoDB에서 검색 (Pinecone 결과와 추가 메타데이터 검색)
#     mongo_query = {
#         "$or": [
#             {"recipe_id": {"$in": list(pinecone_data.keys())}}, 
#             {"title": {"$regex": query, "$options": "i"}},
#             {"ingredients": {"$regex": query, "$options": "i"}},
#             {"instructions": {"$regex": query, "$options": "i"}}
#         ]
#     }
#     mongo_results = db.recipes.find(mongo_query)
#     mongo_results = [recipes_serializer(recipe) for recipe in mongo_results]
    
#     # print(f"MongoDB Results: {mongo_results}")
    
#     # 정확도를 계산하여 MongoDB 결과에 추가
#     def calculate_accuracy_score(recipe, query):
#         score = 0
#         if query.lower() in recipe['title'].lower():
#             score += 1.0
#         if query.lower() in json.dumps(recipe['ingredients'], ensure_ascii=False).lower():
#             score += 0.5
#         if query.lower() in ' '.join(recipe['instructions']).lower():
#             score += 0.5
#         return score

#     for result in mongo_results:
#         result['accuracy_score'] = calculate_accuracy_score(result, query)
        
#    # Pinecone 결과와 MongoDB 결과 결합 및 유사도 점수 추가
#     combined_results = []
#     for result in mongo_results:
#         recipe_id = result['recipe_id']
#         if recipe_id in pinecone_data:
#             result['similarity_score'] = pinecone_data[recipe_id]
#         else:
#             result['similarity_score'] = 0  # MongoDB 결과는 유사도 점수가 없음
#         combined_results.append(result)
    
#     # 정확도 점수와 유사도 점수를 합산하여 정렬
#     combined_results.sort(key=lambda x: (x['accuracy_score'], x['similarity_score']), reverse=True)
    
#     return combined_results

    
# from haystack.document_stores import ElasticsearchDocumentStore
# from haystack.nodes import EmbeddingRetriever
# from haystack.pipelines import DocumentSearchPipeline
# from sentence_transformers import SentenceTransformer
    
# document_store = ElasticsearchDocumentStore(
#     host='elasticsearch',
#     username='',
#     password='',
#     index='recipes'
# )

