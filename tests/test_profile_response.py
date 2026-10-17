import unittest
from types import SimpleNamespace
from app.schemas.auth_schema import UserBase
class ProfileResponseTests(unittest.TestCase):
    def test_editable_profile_fields_survive_auth_response(self):
        user=SimpleNamespace(id="test-id",email="test@example.com",full_name="Test",role="USER",avatar_url=None,job_title="Analista",bio="Perfil de prueba",phone="123",is_active=True,last_login=None)
        result=UserBase.model_validate(user,from_attributes=True).model_dump()
        self.assertEqual(result["job_title"],"Analista")
        self.assertEqual(result["bio"],"Perfil de prueba")
        self.assertEqual(result["phone"],"123")
if __name__=="__main__":unittest.main()
