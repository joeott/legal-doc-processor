import pytest
from unittest.mock import patch, MagicMock, ANY
import uuid
from datetime import datetime, timezone, timedelta

from pydantic import BaseModel, ValidationError

# Subject under test
from scripts.db import PydanticDatabase, PydanticSerializer, DatabaseManager, ProcessingStatus

# Sample Pydantic model for testing
from scripts.core.schemas import ProjectModel, SourceDocumentModel # Added SourceDocumentModel

# A simpler model for some tests if ProjectModel is too complex initially
class SimpleTestModel(BaseModel):
    id: uuid.UUID
    name: str
    value: int
    created_at: datetime
    meta: dict = {}
    optional_field: str = None


class AnotherSimpleModel(BaseModel):
    item_id: int
    description: str

# Global test data
TEST_UUID = uuid.uuid4()
TEST_DATETIME_NAIVE = datetime.now()
TEST_DATETIME_AWARE = datetime.now(timezone.utc)
TEST_PROJECT_ID_DB = uuid.uuid4()
TEST_PROJECT_NAME_DB = "DB Project"


class TestPydanticSerializer:
    def test_deserialize_valid_data(self):
        data = {
            "id": str(TEST_UUID),
            "name": "Test Name",
            "value": 123,
            "created_at": TEST_DATETIME_AWARE.isoformat(),
            "meta": {"key": "value"},
            "optional_field": "present"
        }
        # Fix: Correct parameter order - data first, then model_class
        model_instance = PydanticSerializer.deserialize(data, SimpleTestModel)
        assert isinstance(model_instance, SimpleTestModel)
        assert model_instance.id == TEST_UUID
        assert model_instance.name == "Test Name"
        assert model_instance.value == 123
        assert model_instance.created_at == TEST_DATETIME_AWARE
        assert model_instance.meta == {"key": "value"}
        assert model_instance.optional_field == "present"

    def test_deserialize_empty_strings_to_none(self):
        data = {
            "id": str(TEST_UUID),
            "name": "Test Name",
            "value": 123,
            "created_at": TEST_DATETIME_AWARE.isoformat(),
            "meta": {"key": ""}, # Empty string in dict should remain
            "optional_field": "" # This should become None if model field is Optional[str]
        }
        # The serializer has logic to convert "" to None
        model_instance = PydanticSerializer.deserialize(data, SimpleTestModel)
        assert model_instance.id == TEST_UUID
        assert model_instance.name == "Test Name" # Required, so "" would error if not allowed by model
        assert model_instance.meta == {"key": ""} # Serializer does not recurse into dicts for "" -> None
        
        # The PydanticSerializer converts "" to None in the cleaned dict
        assert model_instance.optional_field is None


    def test_deserialize_invalid_data_raises_validation_error(self):
        invalid_data = {
            "id": "not-a-uuid",
            "name": "Test Name",
            "value": "not-an-int",
            "created_at": "not-a-datetime"
        }
        with pytest.raises(ValidationError):
            PydanticSerializer.deserialize(invalid_data, SimpleTestModel)

    def test_deserialize_missing_required_field_raises_validation_error(self):
        data_missing_name = {
            "id": str(TEST_UUID),
            "value": 123,
            "created_at": TEST_DATETIME_AWARE.isoformat()
        }
        with pytest.raises(ValidationError) as exc_info:
            PydanticSerializer.deserialize(data_missing_name, SimpleTestModel)
        assert "Field required" in str(exc_info.value)
        assert "name" in str(exc_info.value)

    def test_deserialize_with_project_model_and_aliases(self):
        # ProjectModel uses aliases (e.g., projectId for project_id)
        # When deserializing from DB, we use model field names (not aliases)
        model_data_for_deserialize = {
            "project_id": str(TEST_PROJECT_ID_DB), # Model field name
            "name": TEST_PROJECT_NAME_DB,
            "created_at": TEST_DATETIME_AWARE.isoformat(), # Model field name
            "updated_at": TEST_DATETIME_AWARE.isoformat(), # Model field name
            "script_run_count": 5, # Model field name
            "processed_by_scripts": True,
            "airtable_id": "recTest123",
            "metadata": '{"source": "db"}',
            "active": False,
            # "id": 1, # This is BaseTimestampModel.id, SQL PK
        }

        project = PydanticSerializer.deserialize(model_data_for_deserialize, ProjectModel)
        assert project.project_id == TEST_PROJECT_ID_DB
        assert project.name == TEST_PROJECT_NAME_DB
        assert project.created_at == TEST_DATETIME_AWARE
        assert project.script_run_count == 5
        assert project.metadata == {"source": "db"} # Validator should parse JSON string
        assert project.active is False

    def test_deserialize_empty_string_for_non_optional_field_raises_error(self):
        data = {
            "id": str(TEST_UUID),
            "name": "", # name is not Optional[str], it's str
            "value": 123,
            "created_at": TEST_DATETIME_AWARE.isoformat(),
        }
        # SimpleTestModel.name is `str`, not `Optional[str]`.
        # The serializer converts "" to None, but None is not valid for a required str field
        # Actually, looking at the serializer, it only converts "" to None, so this becomes {"name": None}
        # which will fail validation for a required str field
        with pytest.raises(ValidationError) as exc_info:
            PydanticSerializer.deserialize(data, SimpleTestModel)
        assert "none is not an allowed value" in str(exc_info.value).lower() or "field required" in str(exc_info.value).lower()


class TestPydanticDatabaseSerialize:
    def test_serialize_for_db_simple_model(self):
        instance = SimpleTestModel(
            id=TEST_UUID,
            name="Test Name",
            value=123,
            created_at=TEST_DATETIME_AWARE,
            meta={"key": "value", "nested_list": [1, 2, {"sub_key": "sub_val"}]},
            optional_field=None
        )

        # PydanticDatabase instance is needed to call serialize_for_db
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer) # Engine not used for this

        serialized_data = db.serialize_for_db(instance)

        assert serialized_data["id"] == str(TEST_UUID)
        assert serialized_data["name"] == "Test Name"
        assert serialized_data["value"] == 123
        assert serialized_data["created_at"] == TEST_DATETIME_AWARE.isoformat()

        # Nested dict/list should be JSON stringified by PydanticJSONEncoder via model_dump(mode='json')
        # The PydanticSerializer itself doesn't use PydanticJSONEncoder, but model_dump(mode='json') does.
        # PydanticDatabase.serialize_for_db calls model.model_dump(mode='json', by_alias=True)
        assert isinstance(serialized_data["meta"], str)
        import json
        assert json.loads(serialized_data["meta"]) == {"key": "value", "nested_list": [1, 2, {"sub_key": "sub_val"}]}

        assert serialized_data["optional_field"] is None # None values preserved

    def test_serialize_for_db_with_project_model_aliases(self):
        project_instance = ProjectModel(
            project_id=TEST_PROJECT_ID_DB,
            name=TEST_PROJECT_NAME_DB,
            created_at=TEST_DATETIME_AWARE,
            updated_at=TEST_DATETIME_AWARE,
            script_run_count=10,
            metadata={"detail": "some_info", "complex": {"a": [1,2]}},
            airtable_id=None # Test None preservation for optional field
        )

        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        serialized_data = db.serialize_for_db(project_instance)

        # Check for aliased fields (db column names)
        assert serialized_data["projectId"] == str(TEST_PROJECT_ID_DB)
        assert serialized_data["name"] == TEST_PROJECT_NAME_DB # name has no alias
        assert serialized_data["createdAt"] == TEST_DATETIME_AWARE.isoformat()
        assert serialized_data["updatedAt"] == TEST_DATETIME_AWARE.isoformat()
        assert serialized_data["scriptRunCount"] == 10

        assert isinstance(serialized_data["metadata"], str)
        import json
        assert json.loads(serialized_data["metadata"]) == {"detail": "some_info", "complex": {"a": [1,2]}}

        assert serialized_data["airtable_id"] is None # None value preserved
        assert "active" in serialized_data # Default included, True
        assert serialized_data["active"] is True


    def test_serialize_for_db_preserves_none_values(self):
        instance = SimpleTestModel(
            id=TEST_UUID,
            name="Test None",
            value=456,
            created_at=TEST_DATETIME_NAIVE, # Naive datetime test
            optional_field=None
        )
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        serialized_data = db.serialize_for_db(instance)

        assert serialized_data["optional_field"] is None
        # Naive datetime should also be isoformatted. Pydantic handles this.
        assert serialized_data["created_at"] == TEST_DATETIME_NAIVE.isoformat()

    def test_serialize_for_db_handles_empty_dict_and_list(self):
        instance = SimpleTestModel(
            id=TEST_UUID,
            name="Test Empty Collections",
            value=789,
            created_at=TEST_DATETIME_AWARE,
            meta={} # Empty dict
        )
        # Assuming SimpleTestModel could have an empty list field if added
        # For now, meta={} is the test.

        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        serialized_data = db.serialize_for_db(instance)

        assert isinstance(serialized_data["meta"], str)
        import json
        assert json.loads(serialized_data["meta"]) == {}


@patch('scripts.db.insert_record')
class TestPydanticDatabaseCreate:
    def test_create_returning_true(self, mock_insert_record: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)

        # Input model instance
        input_model_data = SimpleTestModel(
            id=TEST_UUID,
            name="Create Test",
            value=100,
            created_at=TEST_DATETIME_AWARE,
            meta={"feature": "test_create"}
        )

        # Expected data after serialization for insert_record
        # This is what db.serialize_for_db(input_model_data) would produce
        # For SimpleTestModel, there are no aliases, so keys are field names.
        # meta will be json stringified.
        expected_serialized_data = {
            "id": str(TEST_UUID),
            "name": "Create Test",
            "value": 100,
            "created_at": TEST_DATETIME_AWARE.isoformat(),
            "meta": '{"feature": "test_create"}', # JSON string
            "optional_field": None
        }

        # Mock return value from insert_record (raw DB row dict)
        # This should be what the DB returns, typically with DB column names (if different from model field names)
        # For SimpleTestModel, assume DB column names match model field names for this part of the test.
        mock_db_return_row = {
            "id": str(TEST_UUID), # Usually returned from DB
            "name": "Create Test From DB", # Could be different if DB modifies
            "value": 100,
            "created_at": TEST_DATETIME_AWARE.isoformat(),
            "meta": '{"feature": "test_create"}', # DB returns JSON string
            "optional_field": None
        }
        mock_insert_record.return_value = mock_db_return_row

        table_name = "simple_test_models"
        created_model = db.create(input_model_data, table_name, returning=True)

        # 1. Assert serialize_for_db was effectively called (by checking mock_insert_record args)
        mock_insert_record.assert_called_once()
        args, kwargs = mock_insert_record.call_args
        assert args[0] == table_name
        assert args[1] == expected_serialized_data # Data passed to insert_record
        assert kwargs.get('engine') is not None # Engine was passed

        # 2. Assert PydanticSerializer.deserialize was effectively called on the result
        assert isinstance(created_model, SimpleTestModel)
        assert created_model.id == TEST_UUID
        assert created_model.name == "Create Test From DB" # Deserialized from mock_db_return_row
        assert created_model.meta == {"feature": "test_create"} # Deserialized from JSON string

    def test_create_returning_false(self, mock_insert_record: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        input_model_data = SimpleTestModel(id=TEST_UUID, name="No Return", value=200, created_at=TEST_DATETIME_AWARE)

        expected_serialized_data = db.serialize_for_db(input_model_data) # Get exact expected

        mock_insert_record.return_value = None # Or some non-dict value if DB doesn't return rows for INSERT without RETURNING
                                            # For this test, insert_record's return is irrelevant if returning=False

        table_name = "simple_test_models"
        result = db.create(input_model_data, table_name, returning=False)

        mock_insert_record.assert_called_once_with(table_name, expected_serialized_data, engine=ANY)
        assert result is None

    def test_create_with_project_model_aliases_returning_true(self, mock_insert_record: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        project_instance = ProjectModel(
            project_id=TEST_PROJECT_ID_DB,
            name=TEST_PROJECT_NAME_DB,
            created_at=TEST_DATETIME_AWARE,
            updated_at=TEST_DATETIME_AWARE,
            metadata={"k": "v"}
        )

        # This is what serialize_for_db would produce (with aliases)
        expected_serialized_data_for_insert = {
            "projectId": str(TEST_PROJECT_ID_DB),
            "name": TEST_PROJECT_NAME_DB,
            "createdAt": TEST_DATETIME_AWARE.isoformat(),
            "updatedAt": TEST_DATETIME_AWARE.isoformat(),
            "scriptRunCount": 0, # Default
            "processedByScripts": False, # Default
            "data_layer": None, # Default
            "airtable_id": None, # Default
            "metadata": '{}', # JSON string - empty dict default
            "active": True, # Default
            "id": None, # Default from BaseTimestampModel
            "last_synced_at": None, # Default
            "supabaseProjectId": None, # Default
        }

        # DB returns row with DB column names (which are the aliases)
        mock_db_return_row_with_aliases = {
            "id": 12345, # SQL PK
            "projectId": str(TEST_PROJECT_ID_DB),
            "name": "Updated " + TEST_PROJECT_NAME_DB, # Name updated by DB trigger for example
            "createdAt": TEST_DATETIME_AWARE.isoformat(),
            "updatedAt": (TEST_DATETIME_AWARE + timedelta(seconds=1)).isoformat(),
            "scriptRunCount": 1,
            "processedByScripts": False,
            "airtable_id": "recXYZ",
            "metadata": '{"k": "v", "db_added": "yes"}',
            "active": True
        }
        mock_insert_record.return_value = mock_db_return_row_with_aliases

        table_name = "projects" # Assume this table name exists in mappings if using reverse_map

        # For PydanticSerializer.deserialize to work correctly without reverse_map_from_db,
        # the keys from mock_db_return_row_with_aliases must match model field names, not aliases.
        # This is a crucial point. If insert_record returns aliased keys, deserialize needs reverse_map.
        # The PydanticDatabase.create method currently does:
        #   db_row = insert_record(...)
        #   return self.serializer.deserialize(db_row, model_instance.__class__, table_name=table_name)
        # So, if table_name is passed, PydanticSerializer *will* use reverse_map_from_db.
        # For this test, we need to decide if we mock enhanced_column_mappings or provide data accordingly.
        # Let's assume enhanced_column_mappings.reverse_map_from_db correctly turns aliased keys to field names.

        # So, PydanticSerializer.deserialize would receive something like:
        # (after reverse_map_from_db if it was mocked and used)
        # For now, let's assume deserialize gets the DB row as is, and we are testing if it *would* call reverse_map
        # by passing table_name.

        # To simplify, let's assume for *this specific test* that PydanticSerializer.deserialize
        # is robust enough or that we are primarily testing the flow and insert_record call here.
        # The actual deserialization correctness with aliasing is more for TestPydanticSerializer.
        # Here we focus on PydanticDatabase.create behavior.

        # Let's refine the mock for PydanticSerializer.deserialize for this specific test context
        # to isolate what PydanticDatabase.create does.

        deserialized_project_mock = ProjectModel(
            id=12345,
            project_id=TEST_PROJECT_ID_DB,
            name="Updated " + TEST_PROJECT_NAME_DB,
            created_at=TEST_DATETIME_AWARE,
            updated_at=TEST_DATETIME_AWARE + timedelta(seconds=1),
            script_run_count=1,
            processed_by_scripts=False,
            airtable_id="recXYZ",
            metadata={"k": "v", "db_added": "yes"},
            active=True
        )

        with patch.object(PydanticSerializer, 'deserialize', return_value=deserialized_project_mock) as mock_deserialize:
            created_project = db.create(project_instance, table_name, returning=True)

            mock_insert_record.assert_called_once()
            call_args = mock_insert_record.call_args[0]
            assert call_args[0] == table_name
            # Check a few key items in the serialized data passed to insert_record
            assert call_args[1]['projectId'] == expected_serialized_data_for_insert['projectId']
            assert call_args[1]['name'] == expected_serialized_data_for_insert['name']
            assert call_args[1]['metadata'] == expected_serialized_data_for_insert['metadata']

            # Fix: Correct parameter order for deserialize
            mock_deserialize.assert_called_once_with(mock_db_return_row_with_aliases, ProjectModel, table_name=table_name)
            assert created_project == deserialized_project_mock


    def test_create_db_error(self, mock_insert_record: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        input_model_data = SimpleTestModel(id=TEST_UUID, name="Error Test", value=300, created_at=TEST_DATETIME_AWARE)

        mock_insert_record.side_effect = Exception("Simulated DB error (e.g., connection failed, constraint violation)")

        table_name = "simple_test_models"
        with pytest.raises(Exception) as exc_info:
            db.create(input_model_data, table_name, returning=True)

        assert "Simulated DB error" in str(exc_info.value)
        mock_insert_record.assert_called_once() # Ensure it was at least called


@patch('scripts.db.select_records')
class TestPydanticDatabaseGet:
    def test_get_record_found(self, mock_select_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)

        table_name = "simple_test_models"
        filters = {"name": "Get Test"}

        # Mock DB row returned by select_records
        mock_db_row = {
            "id": str(TEST_UUID),
            "name": "Get Test",
            "value": 300,
            "created_at": TEST_DATETIME_AWARE.isoformat(),
            "meta": '{}', # JSON string from DB
            "optional_field": "some_value"
        }
        mock_select_records.return_value = [mock_db_row] # select_records returns a list

        # Expected deserialized model
        expected_model = SimpleTestModel(
            id=TEST_UUID,
            name="Get Test",
            value=300,
            created_at=TEST_DATETIME_AWARE,
            meta={},
            optional_field="some_value"
        )

        # Mock PydanticSerializer.deserialize for this test to ensure it's called correctly
        with patch.object(PydanticSerializer, 'deserialize', return_value=expected_model) as mock_deserialize:
            retrieved_model = db.get(SimpleTestModel, table_name, filters)

            mock_select_records.assert_called_once_with(
                table_name=table_name,
                filters=filters,
                engine=ANY,
                limit=1
            )
            # Fix: Correct parameter order
            mock_deserialize.assert_called_once_with(mock_db_row, SimpleTestModel, table_name=table_name)
            assert retrieved_model == expected_model

    def test_get_record_not_found(self, mock_select_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)

        table_name = "simple_test_models"
        filters = {"name": "NonExistent"}

        mock_select_records.return_value = [] # select_records returns empty list when not found

        retrieved_model = db.get(SimpleTestModel, table_name, filters)

        mock_select_records.assert_called_once_with(
            table_name=table_name,
            filters=filters,
            engine=ANY,
            limit=1
        )
        assert retrieved_model is None

    def test_get_record_not_found_select_returns_none(self, mock_select_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"
        filters = {"name": "NonExistent"}
        mock_select_records.return_value = None # some db utils might return None directly

        retrieved_model = db.get(SimpleTestModel, table_name, filters)

        mock_select_records.assert_called_once_with(table_name=table_name, filters=filters, engine=ANY, limit=1)
        assert retrieved_model is None

    def test_get_db_error(self, mock_select_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)

        table_name = "simple_test_models"
        filters = {"name": "Error Case"}

        mock_select_records.side_effect = Exception("Simulated DB selection error")

        with pytest.raises(Exception) as exc_info:
            db.get(SimpleTestModel, table_name, filters)

        assert "Simulated DB selection error" in str(exc_info.value)
        mock_select_records.assert_called_once_with(
            table_name=table_name,
            filters=filters,
            engine=ANY,
            limit=1
        )

    def test_get_with_project_model_aliases(self, mock_select_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "projects"
        filters = {"projectId": str(TEST_PROJECT_ID_DB)} # Filter using aliased name / DB column name

        # Mock DB row from select_records (using DB column names / aliases)
        mock_db_row_aliased = {
            "id": 1,
            "projectId": str(TEST_PROJECT_ID_DB),
            "name": TEST_PROJECT_NAME_DB,
            "createdAt": TEST_DATETIME_AWARE.isoformat(),
            "updatedAt": TEST_DATETIME_AWARE.isoformat(),
            "metadata": '{"source": "db_get"}'
            # ... other fields
        }
        mock_select_records.return_value = [mock_db_row_aliased]

        # Expected deserialized model (after PydanticSerializer.deserialize handles it)
        expected_project = ProjectModel(
            id=1,
            project_id=TEST_PROJECT_ID_DB,
            name=TEST_PROJECT_NAME_DB,
            created_at=TEST_DATETIME_AWARE,
            updated_at=TEST_DATETIME_AWARE,
            metadata={"source": "db_get"}
        )

        with patch.object(PydanticSerializer, 'deserialize', return_value=expected_project) as mock_deserialize:
            retrieved_project = db.get(ProjectModel, table_name, filters)

            mock_select_records.assert_called_once_with(
                table_name=table_name,
                filters=filters, # Filters are passed as-is to select_records
                engine=ANY,
                limit=1
            )
            # PydanticSerializer.deserialize is called with the raw DB row (aliased keys) and table_name
            # It's the serializer's job (with reverse_map_from_db) to handle the aliased keys.
            # Fix: Correct parameter order
            mock_deserialize.assert_called_once_with(mock_db_row_aliased, ProjectModel, table_name=table_name)
            assert retrieved_project == expected_project


@patch('scripts.db.update_record')
class TestPydanticDatabaseUpdate:
    def test_update_returning_true(self, mock_update_record: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"

        model_to_update = SimpleTestModel(
            id=TEST_UUID,
            name="Updated Name",
            value=101,
            created_at=TEST_DATETIME_AWARE, # Should not change if match_fields is id
            meta={"new_key": "new_value"}
        )
        match_fields = ["id"] # Update where id matches

        # Data that serialize_for_db would produce from model_to_update
        expected_serialized_data = {
            "id": str(TEST_UUID),
            "name": "Updated Name",
            "value": 101,
            "created_at": TEST_DATETIME_AWARE.isoformat(),
            "meta": '{"new_key": "new_value"}',
            "optional_field": None
        }

        # DB returns the updated row (or list of rows if multiple were updated)
        mock_db_return_row = {
            "id": str(TEST_UUID),
            "name": "Updated Name From DB", # Potentially modified by DB
            "value": 101,
            "created_at": TEST_DATETIME_AWARE.isoformat(), # Original creation time
            "meta": '{"new_key": "new_value", "db_flag": true}',
            "optional_field": "updated_by_db"
        }
        mock_update_record.return_value = [mock_db_return_row] # update_record returns a list of dicts

        expected_deserialized_model = SimpleTestModel(
            id=TEST_UUID,
            name="Updated Name From DB",
            value=101,
            created_at=TEST_DATETIME_AWARE,
            meta={"new_key": "new_value", "db_flag": True},
            optional_field="updated_by_db"
        )

        with patch.object(PydanticSerializer, 'deserialize', return_value=expected_deserialized_model) as mock_deserialize:
            updated_model = db.update(model_to_update, table_name, match_fields, returning=True)

            mock_update_record.assert_called_once()
            args, kwargs = mock_update_record.call_args
            assert args[0] == table_name
            assert args[1] == match_fields
            assert args[2] == expected_serialized_data # data for update
            assert kwargs.get('engine') is not None

            # Fix: Correct parameter order
            mock_deserialize.assert_called_once_with(mock_db_return_row, SimpleTestModel, table_name=table_name)
            assert updated_model == expected_deserialized_model

    def test_update_returning_true_no_records_updated(self, mock_update_record: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"
        model_to_update = SimpleTestModel(id=TEST_UUID, name="No Match", value=102, created_at=TEST_DATETIME_AWARE)
        match_fields = ["id"]

        mock_update_record.return_value = [] # DB updated 0 rows

        with patch.object(PydanticSerializer, 'deserialize') as mock_deserialize:
            updated_model = db.update(model_to_update, table_name, match_fields, returning=True)
            assert updated_model is None
            mock_deserialize.assert_not_called() # Deserialize should not be called if no records returned

    def test_update_returning_false(self, mock_update_record: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"
        model_to_update = SimpleTestModel(id=TEST_UUID, name="Update No Return", value=103, created_at=TEST_DATETIME_AWARE)
        match_fields = ["id"]

        expected_serialized_data = db.serialize_for_db(model_to_update)
        mock_update_record.return_value = None # Irrelevant for returning=False or might be row count for some dbs

        result = db.update(model_to_update, table_name, match_fields, returning=False)

        mock_update_record.assert_called_once()
        args, kwargs = mock_update_record.call_args
        assert args[0] == table_name
        assert args[1] == match_fields
        assert args[2] == expected_serialized_data
        assert result is None

    def test_update_db_error(self, mock_update_record: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"
        model_to_update = SimpleTestModel(id=TEST_UUID, name="Update Error", value=104, created_at=TEST_DATETIME_AWARE)
        match_fields = ["id"]

        mock_update_record.side_effect = Exception("Simulated DB update error")

        with pytest.raises(Exception) as exc_info:
            db.update(model_to_update, table_name, match_fields, returning=True)

        assert "Simulated DB update error" in str(exc_info.value)
        mock_update_record.assert_called_once()


@patch('scripts.db.select_records')
class TestPydanticDatabaseList:
    def test_list_records_found(self, mock_select_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"
        filters = {"value": pytest.approx(10.0, 0.1)} # Example filter
        order_by = "created_at DESC"
        limit = 10

        mock_db_rows = [
            {"id": str(uuid.uuid4()), "name": "List Item 1", "value": 10, "created_at": TEST_DATETIME_AWARE.isoformat()},
            {"id": str(uuid.uuid4()), "name": "List Item 2", "value": 10, "created_at": (TEST_DATETIME_AWARE - timedelta(days=1)).isoformat()}
        ]
        mock_select_records.return_value = mock_db_rows

        # Mock deserialized objects that PydanticSerializer.deserialize would return for each row
        deserialized_models = [
            SimpleTestModel.model_validate(row) for row in mock_db_rows # Simplified for this test
        ]

        with patch.object(PydanticSerializer, 'deserialize', side_effect=deserialized_models) as mock_deserialize:
            results = db.list(SimpleTestModel, table_name, filters=filters, limit=limit, order_by=order_by)

            mock_select_records.assert_called_once_with(
                table_name=table_name,
                filters=filters,
                engine=ANY,
                order_by=order_by,
                limit=limit
            )
            assert mock_deserialize.call_count == len(mock_db_rows)
            for i, row in enumerate(mock_db_rows):
                # Fix: Correct parameter order
                mock_deserialize.assert_any_call(row, SimpleTestModel, table_name=table_name)

            assert len(results) == len(deserialized_models)
            for i, model in enumerate(results):
                assert model.name == deserialized_models[i].name # Check a field

    def test_list_no_records_found(self, mock_select_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"
        mock_select_records.return_value = [] # Empty list for no records

        results = db.list(SimpleTestModel, table_name)
        assert results == []
        mock_select_records.assert_called_once()

    @patch('scripts.db.logger.warning') # Mock logger for checking warnings
    def test_list_record_deserialization_error_skips_record(self, mock_logger_warning: MagicMock, mock_select_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"

        valid_row = {"id": str(uuid.uuid4()), "name": "Valid Item", "value": 1, "created_at": TEST_DATETIME_AWARE.isoformat()}
        invalid_row_type = {"id": str(uuid.uuid4()), "name": "Invalid Type", "value": "not-an-int", "created_at": TEST_DATETIME_AWARE.isoformat()}

        mock_select_records.return_value = [valid_row, invalid_row_type]

        # PydanticSerializer.deserialize will be called. Let its normal behavior occur.
        # It will raise ValidationError for invalid_row_type.

        results = db.list(SimpleTestModel, table_name)

        assert len(results) == 1 # Only the valid record should be returned
        assert results[0].name == "Valid Item"

        mock_logger_warning.assert_called_once()
        args, _ = mock_logger_warning.call_args
        assert "Failed to deserialize record" in args[0]
        assert "invalid_row_type" in args[0].lower() or "not-an-int" in args[0].lower() # Check if problematic data is mentioned

    def test_list_db_error(self, mock_select_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"
        mock_select_records.side_effect = Exception("Simulated DB list error")

        with pytest.raises(Exception) as exc_info:
            db.list(SimpleTestModel, table_name)

        assert "Simulated DB list error" in str(exc_info.value)
        mock_select_records.assert_called_once()


@patch('scripts.db.delete_records')
class TestPydanticDatabaseDelete:
    def test_delete_success(self, mock_delete_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer) # Serializer not used by delete
        table_name = "simple_test_models"
        match_fields = {"name": "To Be Deleted"}

        mock_delete_records.return_value = 1 # Simulate 1 record deleted

        deleted_count = db.delete(table_name, match_fields)

        mock_delete_records.assert_called_once_with(
            table_name=table_name,
            filters=match_fields,
            engine=ANY
        )
        assert deleted_count == 1

    def test_delete_no_records_match(self, mock_delete_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"
        match_fields = {"name": "No Such Record"}

        mock_delete_records.return_value = 0 # Simulate 0 records deleted

        deleted_count = db.delete(table_name, match_fields)
        assert deleted_count == 0
        mock_delete_records.assert_called_once()

    def test_delete_db_error(self, mock_delete_records: MagicMock):
        db = PydanticDatabase(engine=MagicMock(), serializer=PydanticSerializer)
        table_name = "simple_test_models"
        match_fields = {"name": "Delete Error Case"}

        mock_delete_records.side_effect = Exception("Simulated DB delete error")

        with pytest.raises(Exception) as exc_info:
            db.delete(table_name, match_fields)

        assert "Simulated DB delete error" in str(exc_info.value)
        mock_delete_records.assert_called_once()


# Mock the ConformanceValidator before it's imported by scripts.db
MOCK_CONFORMANCE_VALIDATOR_PATH = 'scripts.core.conformance_validator.ConformanceValidator'

@patch('scripts.db.DatabaseManager.validate_conformance')
class TestDatabaseManagerInit:
    def test_init_calls_validate_conformance_by_default(self, mock_validate_conformance: MagicMock):
        db_manager = DatabaseManager(engine=MagicMock(), pydantic_db=MagicMock())
        mock_validate_conformance.assert_called_once()
        assert db_manager.conformance_validated is False # validate_conformance sets this

    def test_init_skips_validate_conformance_if_false(self, mock_validate_conformance: MagicMock):
        db_manager = DatabaseManager(engine=MagicMock(), pydantic_db=MagicMock(), validate_conformance_on_init=False)
        mock_validate_conformance.assert_not_called()
        assert db_manager.conformance_validated is False # Stays false if not called


class TestDatabaseManagerConformanceValidation:
    @patch(MOCK_CONFORMANCE_VALIDATOR_PATH)
    def test_validate_conformance_success(self, MockConformanceValidatorClass: MagicMock):
        mock_validator_instance = MockConformanceValidatorClass.return_value
        mock_validator_instance.validate_with_recovery.return_value = MagicMock(success=True)

        db_manager = DatabaseManager(engine=MagicMock(), pydantic_db=MagicMock(), validate_conformance_on_init=False)
        db_manager.validate_conformance() # Call directly

        MockConformanceValidatorClass.assert_called_once_with(db_manager.pydantic_db)
        mock_validator_instance.validate_with_recovery.assert_called_once()
        assert db_manager.conformance_validated is True

    @patch(MOCK_CONFORMANCE_VALIDATOR_PATH)
    def test_validate_conformance_failure_raises_error(self, MockConformanceValidatorClass: MagicMock):
        from scripts.db import ConformanceError # Import here to avoid issues if scripts.db itself fails on import

        mock_validator_instance = MockConformanceValidatorClass.return_value
        mock_report = MagicMock(success=False, errors=["Schema mismatch"], summary="Validation failed")
        mock_validator_instance.validate_with_recovery.return_value = mock_report

        db_manager = DatabaseManager(engine=MagicMock(), pydantic_db=MagicMock(), validate_conformance_on_init=False)

        with pytest.raises(ConformanceError) as exc_info:
            db_manager.validate_conformance()

        assert "Database schema conformance validation failed." in str(exc_info.value)
        assert "Schema mismatch" in str(exc_info.value)
        assert db_manager.conformance_validated is False

    @patch('scripts.db.logger.warning')
    @patch.dict('sys.modules', {'scripts.core.conformance_validator': None}) # Simulate ImportError
    def test_validate_conformance_importerror_logs_warning(self, mock_logger_warning: MagicMock):
        # Need to reload scripts.db or ensure DatabaseManager is defined in a way that
        # the import of ConformanceValidator happens *during* validate_conformance call
        # or at least when ConformanceValidator is first accessed within it.

        # The current DatabaseManager imports ConformanceValidator at the top level.
        # So, to test this, we'd need to patch 'scripts.db.ConformanceValidator' to be None.

        with patch('scripts.db.ConformanceValidator', None): # Patch the imported name in scripts.db
            db_manager = DatabaseManager(engine=MagicMock(), pydantic_db=MagicMock(), validate_conformance_on_init=False)
            db_manager.validate_conformance() # Call directly

            mock_logger_warning.assert_called_once()
            assert "ConformanceValidator not found or import failed" in mock_logger_warning.call_args[0][0]
            assert "Database schema conformance will not be validated." in mock_logger_warning.call_args[0][0]
            assert db_manager.conformance_validated is True # Degraded mode, validation "passes"


class TestDatabaseManagerHelperMethods:
    def test_get_project_by_id(self):
        mock_pydantic_db = MagicMock(spec=PydanticDatabase)
        db_manager = DatabaseManager(engine=MagicMock(), pydantic_db=mock_pydantic_db, validate_conformance_on_init=False)

        project_id_to_get = 123
        expected_project = ProjectModel(id=project_id_to_get, name="Test Project", project_id=uuid.uuid4(), created_at=datetime.now(), updated_at=datetime.now())
        mock_pydantic_db.get.return_value = expected_project

        result = db_manager.get_project_by_id(project_id_to_get)

        mock_pydantic_db.get.assert_called_once_with(
            ProjectModel,
            "projects",
            {"id": project_id_to_get}
        )
        assert result == expected_project

    def test_get_project_by_project_uuid(self): # Adding another getter for project_id (UUID)
        mock_pydantic_db = MagicMock(spec=PydanticDatabase)
        db_manager = DatabaseManager(engine=MagicMock(), pydantic_db=mock_pydantic_db, validate_conformance_on_init=False)

        project_uuid_to_get = TEST_PROJECT_ID_DB # Global test UUID
        expected_project = ProjectModel(id=1, name="Test Project UUID", project_id=project_uuid_to_get, created_at=datetime.now(), updated_at=datetime.now())
        mock_pydantic_db.get.return_value = expected_project

        result = db_manager.get_project_by_project_uuid(str(project_uuid_to_get)) # Method expects string

        mock_pydantic_db.get.assert_called_once_with(
            ProjectModel,
            "projects",
            {"project_id": str(project_uuid_to_get)} # Ensure it's passed as string if method expects string
        )
        assert result == expected_project

    def test_create_source_document(self):
        mock_pydantic_db = MagicMock(spec=PydanticDatabase)
        db_manager = DatabaseManager(engine=MagicMock(), pydantic_db=mock_pydantic_db, validate_conformance_on_init=False)

        doc_uuid = uuid.uuid4()
        doc_instance = SourceDocumentModel(
            document_uuid=doc_uuid,
            original_file_name="test.pdf",
            detected_file_type="application/pdf",
            created_at=datetime.now(timezone.utc), # Ensure aware for consistency
            updated_at=datetime.now(timezone.utc)
        )

        # Mock the return value of pydantic_db.create
        # pydantic_db.create returns the created model instance if returning=True (default)
        mock_pydantic_db.create.return_value = doc_instance

        result = db_manager.create_source_document(doc_instance)

        # Check that pydantic_db.create was called correctly
        mock_pydantic_db.create.assert_called_once_with(
            doc_instance,
            "source_documents",
            returning=True # Default of create_source_document
        )
        assert result == doc_instance

    @patch('scripts.db.update_record') # Mock the low-level rds_utils function
    def test_update_document_status(self, mock_rds_update_record: MagicMock):
        # db_manager uses its own engine, not the one from pydantic_db for this helper method
        mock_engine = MagicMock()
        db_manager = DatabaseManager(engine=mock_engine, pydantic_db=MagicMock(), validate_conformance_on_init=False)

        doc_uuid_str = str(uuid.uuid4())
        new_status = ProcessingStatus.COMPLETED
        error_msg = "Test error message"

        # Mocking behavior of rds_utils.update_record
        # It returns a list of dicts (updated rows) or an empty list if no match, or raises error.
        # For a successful update of one record, it might return e.g. [{"id": 1, "status": "completed"}]
        # The boolean return of update_document_status depends on if any rows were affected.
        mock_rds_update_record.return_value = [{"document_uuid": doc_uuid_str, "celery_status": new_status.value}] # Simulate one record updated

        # Call the method
        success = db_manager.update_document_status(doc_uuid_str, new_status, error_msg)

        # Assertions
        mock_rds_update_record.assert_called_once()
        args, kwargs = mock_rds_update_record.call_args

        assert args[0] == "source_documents" # table_name
        assert args[1] == ["document_uuid"] # match_fields

        update_data = args[2] # data for update
        assert update_data["document_uuid"] == doc_uuid_str
        assert update_data["celery_status"] == new_status.value
        assert update_data["error_message"] == error_msg
        assert "updated_at" in update_data # Should be updated
        assert isinstance(update_data["updated_at"], str) # Serialized by update_document_status

        # Check if completed_at is set for COMPLETED status
        if new_status == ProcessingStatus.COMPLETED:
            assert "ocr_completed_at" in update_data # Example completed_at field
            assert isinstance(update_data["ocr_completed_at"], str)

        assert kwargs.get('engine') == mock_engine # Engine passed from db_manager
        assert success is True

    @patch('scripts.db.update_record')
    def test_update_document_status_no_record_updated(self, mock_rds_update_record: MagicMock):
        mock_engine = MagicMock()
        db_manager = DatabaseManager(engine=mock_engine, pydantic_db=MagicMock(), validate_conformance_on_init=False)
        doc_uuid_str = str(uuid.uuid4())
        new_status = ProcessingStatus.PROCESSING

        mock_rds_update_record.return_value = [] # Simulate no records updated

        success = db_manager.update_document_status(doc_uuid_str, new_status)

        assert success is False
        mock_rds_update_record.assert_called_once() # Ensure it was called

    @patch('scripts.db.update_record')
    def test_update_document_status_handles_failed_status(self, mock_rds_update_record: MagicMock):
        mock_engine = MagicMock()
        db_manager = DatabaseManager(engine=mock_engine, pydantic_db=MagicMock(), validate_conformance_on_init=False)
        doc_uuid_str = str(uuid.uuid4())
        new_status = ProcessingStatus.FAILED # Example of a "failed" status
        error_msg = "OCR failed catastrophically"

        mock_rds_update_record.return_value = [{"document_uuid": doc_uuid_str}]

        success = db_manager.update_document_status(doc_uuid_str, new_status, error_msg)

        assert success is True
        update_data = mock_rds_update_record.call_args[0][2]
        assert update_data["celery_status"] == new_status.value # or specific mapping if any
        assert update_data["error_message"] == error_msg
        # Check that ocr_completed_at is NOT set for FAILED status
        assert "ocr_completed_at" not in update_data
        # (or is None, depending on model, but this method seems to only add it if COMPLETED)
        # The current `update_document_status` only adds `ocr_completed_at` for `COMPLETED`.