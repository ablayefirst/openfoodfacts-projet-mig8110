def calculate_health_score(row):
    score = 0

    score += -2 * (row["sugars_100g"] or 0)
    score += -3 * (row["salt_100g"] or 0)
    score += -2 * (row["saturated_fat_100g"] or 0)
    score += 2 * (row["fiber_100g"] or 0)
    score += 1 * (row["proteins_100g"] or 0)

    if row["nova_group"] == 4:
        score -= 3

    return score