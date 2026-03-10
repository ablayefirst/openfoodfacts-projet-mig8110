import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, f1_score, confusion_matrix
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, BaggingClassifier, AdaBoostClassifier, GradientBoostingClassifier
from sklearn.naive_bayes import GaussianNB
import xgboost as xgb

data = pd.read_csv("dataset_ml_ready.csv")

X = data.drop("class", axis=1)
y = data["class"]

X_train, X_test, y_train, y_test = train_test_split(
    X,y,test_size=0.2,random_state=42
)

models = {

"DecisionTree": DecisionTreeClassifier(),

"Bagging": BaggingClassifier(),

"AdaBoost": AdaBoostClassifier(),

"GBoost": GradientBoostingClassifier(),

"XGBoost": xgb.XGBClassifier(),

"RandomForest": RandomForestClassifier(),

"NaiveBayes": GaussianNB()

}

results = []

for name,model in models.items():

    model.fit(X_train,y_train)

    preds = model.predict(X_test)

    auc = roc_auc_score(y_test,preds)

    f1 = f1_score(y_test,preds)

    cm = confusion_matrix(y_test,preds)

    TP = cm[1,1]
    FP = cm[0,1]

    results.append([name,TP,FP,f1,auc])

df = pd.DataFrame(results,
columns=["Algorithm","TP Rate","FP Rate","F1","AUC"])

print(df)

df.to_csv("metrics_results.csv",index=False)