import pandas as pd
from googletrans import Translator

df = pd.read_csv("nettoye.csv")

# garder seulement les catégories non vides
df_non_vide = df[df["categories"].notna()]

# échantillon de 500
sample_df = df_non_vide.sample(500, random_state=42)

sample_df["categories"].head(10)

len(sample_df)


#Split categorie en liste
import pandas as pd
import ast
sample_df["categories_list"] = sample_df["categories"].apply(
    lambda x: ast.literal_eval(x) if isinstance(x, str) else []
)

# Aplatir les listes de catégories, supprimer les doublons et calculer le nombre de catégories uniques
import itertools

all_categories = list(itertools.chain.from_iterable(sample_df["categories_list"]))

unique_categories = list(set(all_categories))

print("Nombre de catégories uniques :", len(unique_categories))



translator = Translator()
from googletrans import Translator
import time


#focntion de traduction
translator = Translator()

def traduire(text):
    try:
        time.sleep(0.1)
        return translator.translate(str(text), dest='fr').text
    except:
        return text
translations = {}

for cat in unique_categories:
    translations[cat] = traduire(cat)
sample_df["categories_fr"] = sample_df["categories_list"].apply(
    lambda cats: [translations.get(cat, cat) for cat in cats]
)



#normalisation de cateorie
def normalize_category(cat):

    if pd.isna(cat):
        return None

    cat = cat.lower()

    cat = re.sub(r"[^a-zàâäéèêëîïôöùûüç\s]", " ", cat)

    cat = re.sub(r"\s+", " ", cat)

    return cat.strip()
import re
sample_df["categories_fr"] = sample_df["categories_fr"].apply(
    lambda cats: [normalize_category(cat) for cat in cats]
)

import itertools

all_categories_fr = list(itertools.chain.from_iterable(sample_df["categories_fr"]))
unique_categories_fr = list(set(all_categories_fr))

print(set(all_categories_fr))


# Regrouper les catégories similaires en clusters à l’aide d’une similarité textuelle (fuzzy matching) afin de normaliser les catégories et créer un mapping entre catégories brutes et catégories finales
from rapidfuzz import fuzz, process

clusters = {}

SIMILARITY_THRESHOLD = 80

for cat in unique_categories_fr:

    match = process.extractOne(cat, clusters.keys(), scorer=fuzz.ratio)

    if match and match[1] >= SIMILARITY_THRESHOLD:
        clusters[match[0]].append(cat)

    else:
        clusters[cat] = [cat]
mapping = []

for main_cat, group in clusters.items():

    for g in group:
        mapping.append([g, main_cat])

mapping_df = pd.DataFrame(mapping, columns=["raw_category","final_category"])


# Nettoyer les catégories en supprimant les mots inutiles (stop words) et extraire le mot principal pour faciliter la normalisation
STOP_WORDS = [
"de","à","des","les","du","la","le","et",
"with","and","of",


# mots descriptifs
"organic","fresh","whole","dry","dried","frozen",
"raw","natural","vegan","plant","prepared",
"mix","mixes","mixte"

]
def extract_main_word(cat):

    if not isinstance(cat, str):
        return None

    words = cat.lower().split()

    words = [w for w in words if w not in STOP_WORDS]

    if len(words) == 0:
        return None

    return words[0]
mapping_df["main_category"] = mapping_df["final_category"].apply(extract_main_word)

# Lemmatiser les mots à l’aide de spaCy afin de ramener chaque terme à sa forme de base pour améliorer la normalisation des catégories
import spacy
nlp = spacy.load("en_core_web_sm")
def lemmatize_word(word):

    if not isinstance(word, str):
        return None

    word = word.strip()

    if word == "":
        return None

    doc = nlp(word)

    if len(doc) == 0:
        return None

    return doc[0].lemma_

mapping_df["lemma_category"] = mapping_df["main_category"].apply(lemmatize_word)


BAD_CATEGORIES = [
"can",
"shelf",
"aliment",
"food",
"produit",
"pack",
"prepared",
"plat"
]

mapping_df["clean_category"] = mapping_df["lemma_category"].apply(
    lambda x: None if x in BAD_CATEGORIES else x
)



FOOD_KEYWORDS = {

# produits laitiers
"milk":"produit laitier",
"lait":"produit laitier",
"dairy":"produit laitier",
"produits laitiers":"produit laitier",
"butter":"produit laitier",
"beurre":"produit laitier",
"cream":"produit laitier",
"crème":"produit laitier",
"cheese":"fromage",
"fromage":"fromage",
"yogurt":"yaourt",
"yoghurt":"yaourt",
"yaourt":"yaourt",

# fruits
"fruit":"fruit",
"fruits":"fruit",
"apple":"fruit",
"pomme":"fruit",
"banana":"fruit",
"banane":"fruit",
"orange":"fruit",
"strawberry":"fruit",
"fraise":"fruit",
"watermelon":"fruit",
"pastèque":"fruit",

# légumes
"vegetable":"légume",
"vegetables":"légume",
"légume":"légume",
"légumes":"légume",
"broccoli":"légume",
"brocoli":"légume",
"carrot":"légume",
"carotte":"légume",
"tomato":"légume",
"tomate":"légume",
"onion":"légume",
"oignon":"légume",
"potato": "légume",

"pâtes alimentaires":"pâte",
# viande
"meat":"viande",
"viande":"viande",
"beef":"viande",
"bœuf":"viande",
"pork":"viande",
"porc":"viande",
"chicken":"poulet",
"poulet":"poulet",
"viandes et dérivés":"viande",

"vinegar":"vinaigre",
"vinaigre":"vinaigre",
# poisson
"fish":"poisson",
"poisson":"poisson",
"salmon":"poisson",
"saumon":"poisson",
"tuna":"poisson",
"thon":"poisson",
"produits de la mer":"poisson",

# céréales
"cereal":"céréale",
"cereals":"céréale",
"céréale":"céréale",
"céréales":"céréale",
"rice":"riz",
"riz":"riz",
"bread":"pain",
"pain":"pain",
"pasta":"pâte",
"pâtes":"pâte",

# snacks
"snack":"snack",
"chips":"snack",
"crisps":"snack",

# desserts
"cake":"dessert",
"gâteau":"dessert",
"biscuit":"dessert",
"cookie":"dessert",
"chocolate":"dessert",
"chocolat":"dessert",

# boissons
"drink":"boisson",
"boisson":"boisson",
"beverage":"boisson",
"juice":"jus",
"jus":"jus",

# noix
"almond":"noix",
"amande":"noix",
"pistachio":"noix",
"pistache":"noix",
"peanut":"noix",
"cacahuète":"noix",
"nut":"noix",
"nuts":"noix",

# graines
"seed":"graine",
"graines":"graine",
"seeds":"graine",

# sauces
"sauce":"sauce",
"sauces":"sauce",

# miel
"honey":"miel",
"miel":"miel",

# huile
"oil":"huile",
"huile":"huile",

# boissons chaudes
"tea":"thé",
"thé":"thé",
"coffee":"café",
"café":"café",

# épices
"spice":"épice",
"spices":"épice",
"épice":"épice",
"épices":"épice",

"saucisse":"viande",
"sausage":"viande",
"hamburger":"viande",
"bacon":"viande",

"pizza":"pizza",
"tortilla":"pain",
"sandwich":"pain",

"popcorn":"snack",
"cracker":"snack",
"chip":"snack",

"mayonnaise":"sauce",
"ketchup":"sauce",
"mustard":"sauce",
"moutarde":"sauce",

"olive":"légume",

"quinoa":"céréale",
"oat":"céréale",
"wheat":"céréale",

"smoothie":"boisson",
"soda":"boisson",
"cola":"boisson",

"ice":"dessert",
"glace":"dessert",
"brownie":"dessert",
"muffin":"dessert"

}
mapping_df["clean_category"] = mapping_df["clean_category"].apply(
    lambda x: x.lower().strip() if isinstance(x,str) else x
)

mapping_df["final_category"] = mapping_df["clean_category"].apply(
    lambda x: FOOD_KEYWORDS.get(x, "autres")
)



BAD_WORDS = [
"large","natural","fresh","high","low","special","diet",
"instant","organic","whole","brown","white","extra",
"medium","fine","dark","red","yellow","non","common",
"frozen","dry","None","ça","je","se","fait","base","populaire","calendrier","stylo","b","gro"
]
mapping_df["clean_categoryBad"] = mapping_df["final_category"].apply(
    lambda x: None if x in BAD_WORDS else x
)

FOOD_KEYWORDS.update({

# desserts / sucreries
"bonbon":"dessert",
"confiserie":"dessert",
"gâteaux":"dessert",
"pâtisserie":"dessert",
"macaron":"dessert",
"caramel":"dessert",
"panettone":"dessert",

# céréales / grains
"flocon":"céréale",
"avoine":"céréale",
"gruau":"céréale",
"maïs":"céréale",
"corn":"céréale",
"mueslis":"céréale",
"granola":"céréale",

# pâtes / produits céréaliers
"pâte":"pâte",
"spaghetti":"pâte",
"gnocchi":"pâte",
"gnocchis":"pâte",
"nouille":"pâte",
"udon":"pâte",
"ravioli":"pâte",

# produits laitiers
"laiterie":"produit laitier",
"mozzarella":"fromage",
"cheddar":"fromage",
"feta":"fromage",

# viande / charcuterie
"saucisson":"viande",
"salami":"viande",
"charcuterie":"viande",
"jambon":"viande",
"lard":"viande",
"volaille":"viande",
"canard":"viande",
"cuisse":"viande",
"jerky":"viande",
"foie":"viande",

# poisson
"maquereaux":"poisson",
"morue":"poisson",
"filet":"poisson",

# légumes / végétaux
"haricot":"légumineuse",
"pois":"légumineuse",
"légumineuse":"légumineuse",
"épinar d":"légume",
"épinard":"légume",
"salade":"légume",
"ail":"légume",
"cornichon":"légume",
"pickle":"légume",

# fruits
"mangue":"fruit",
"raisin":"fruit",
"bleuet":"fruit",
"kiwis":"fruit",

# sauces / condiments
"condiment":"sauce",
"vinaigrette":"sauce",
"trempette":"sauce",
"chutney":"sauce",
"pestos":"sauce",

# boissons
"eau":"boisson",
"eaux":"boisson",
"limonade":"boisson",
"kombuchas":"boisson",
"bière":"boisson",
"cafés":"boisson",
"thés":"boisson",

# graines / noix
"graine":"graine",
"chia":"graine",
"noix":"noix",

# produits transformés
"bouillon":"soupe",
"soupe":"soupe",
"repas":"plat",
"ratatouille":"plat",
"tofu":"protéine végétale",
"canneberge":"fruit"

})

mapping_df["final_category"] = mapping_df["clean_category"].apply(
    lambda x: FOOD_KEYWORDS.get(x, x)
)


FOOD_KEYWORDS.update({

"biscuit":"dessert",
"gâteau":"dessert",
"brownie":"dessert",
"muffin":"dessert",
"glace":"dessert",
"macaron":"dessert",

"beurre":"produit laitier",
"crème":"produit laitier",
"lait":"produit laitier",

"pita":"pain",
"brioche":"pain",
"galette":"pain",

"fève":"légumineuse",

"compote":"fruit",

"pita":"pain",

"houmous":"légumineuse"

})
mapping_df["final_category"] = mapping_df["clean_category"].apply(
    lambda x: FOOD_KEYWORDS.get(x, x)
)




VALID_CATEGORIES = [

"boisson","légume","viande","pâte","céréale","poisson","sauce","pain",
"fruit","fromage","noix","poulet","légumineuse","snack","huile","soupe",
"vinaigre","pizza","yaourt","miel","riz","graine",

# AJOUTER

"dessert",
"biscuit",
"lait",
"beurre",
"chocolat",
"glace",
"barre",
"farine",
"sucre"

]

mapping_df["final_category"] = mapping_df["final_category"].apply(
    lambda x: x if x in VALID_CATEGORIES else "autres"
)


CATEGORY_KEYWORDS = {

"boisson":[
"boisson","jus","soda","cola","limonade","smoothie","thé","café","kombucha","eau","bière"
],

"produit laitier":[
"lait","yaourt","beurre","crème","laiterie"
],

"fromage":[
"fromage","mozzarella","cheddar","feta"
],

"viande":[
"viande","boeuf","porc","jambon","saucisse","salami","charcuterie"
],

"poulet":[
"poulet","volaille"
],

"poisson":[
"poisson","thon","saumon","morue","maquereau","fruit de mer"
],

"fruit":[
"fruit","pomme","banane","raisin","mangue","bleuet"
],

"légume":[
"légume","tomate","oignon","épinard","ail","salade"
],

"légumineuse":[
"haricot","pois","lentille"
],

"céréale":[
"céréale","avoine","maïs","granola","muesli"
],

"pain":[
"pain","brioche","pita","bagel","galette"
],

"pâte":[
"pâte","spaghetti","ravioli","gnocchi","nouille","udon"
],

"snack":[
"chips","popcorn","snack","cracker"
],

"dessert":[
"dessert","gâteau","bonbon","biscuit","chocolat","brownie","muffin","glace","macaron"
],

"sauce":[
"sauce","ketchup","mayonnaise","vinaigrette","chutney"
],

"huile":[
"huile","olive","canola"
],

"miel":[
"miel"
],

"vinaigre":[
"vinaigre"
],

"riz":[
"riz"
]

}

CATEGORY_KEYWORDS.update({

# boulangerie / pâtisserie
"boulangerie":[
"viennoiserie","brioche","croissant","pâtisserie","tarte"
],

# farine / ingrédients
"farine":[
"farine","blé","semoule"
],

# sucre
"sucre":[
"sucre","sirop","caramel","édulcorant"
],

# barres alimentaires
"barre":[
"barre","granola bar","protein bar"
],

# soupes
"soupe":[
"soupe","bouillon"
],

# noix / oléagineux
"noix":[
"noix","amande","pistache","cacahuète","noisette"
],

# graines
"graine":[
"graine","chia","lin","sésame"
],

# condiments
"condiment":[
"assaisonnement","épice","moutarde"
],

# plats préparés
"plat":[
"repas","plat","ratatouille"
],
"dessert":[
"dessert","biscuit","gâteau","chocolat","bonbon","glace","brownie","muffin"
],

"pain":[
"pain","brioche","bagel","pita","galette","viennoiserie"
],

"fruit":[
"fruit","compote","baie"
],

"légume":[
"légume","tomate","oignon","épinard","ail","salade"
],

"viande":[
"viande","jambon","saucisse","salami","charcuterie"
],

"snack":[
"chips","popcorn","cracker","collation"
]


})

def classify_category(text):

    if not isinstance(text,str):
        return "autres"

    text = text.lower()

    for category, keywords in CATEGORY_KEYWORDS.items():

        for word in keywords:

            if word in text:
                return category

    return "autres"

mapping_df["final_category"] = mapping_df["raw_category"].apply(classify_category)