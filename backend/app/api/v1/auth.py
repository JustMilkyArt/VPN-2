from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.auth import LoginRequest, TokenResponse, AdminUserCreate, AdminUserRead
from app.models.admin_user import AdminUser
from app.core.security import verify_password, get_password_hash, create_access_token
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(
        AdminUser.username == request.username,
        AdminUser.is_active == True
    ).first()
    
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    token = create_access_token({"sub": user.username})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=AdminUserRead)
def get_me(current_user: AdminUser = Depends(get_current_user)):
    return current_user


@router.post("/users", response_model=AdminUserRead)
def create_user(
    user_data: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    existing = db.query(AdminUser).filter(AdminUser.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    user = AdminUser(
        username=user_data.username,
        password_hash=get_password_hash(user_data.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
