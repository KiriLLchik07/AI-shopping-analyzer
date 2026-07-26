from backend.app.models.user import User

def user_to_dto(user: User) -> dict:
    return {
        "user_id": str(user.user_id),
        "user_name": user.user_name,
        "user_surname": user.user_surname,
        "user_mail": user.user_mail,
        "user_age": user.user_age,
        "user_country": user.user_country,
        "user_city": user.user_city 
    }
