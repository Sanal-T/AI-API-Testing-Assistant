import logging
import re
from typing import Any

from app.generator.testcase_generator import generate_test_cases
from app.models.workflow import VariableExtractor, Workflow, WorkflowStep

logger = logging.getLogger(__name__)


def generate_crud_workflows(endpoints: list[dict[str, Any]]) -> list[Workflow]:
    """Analyze endpoint operations and synthesize full CRUD integration workflows."""
    workflows: list[Workflow] = []

    # 1. Map endpoints by normalized resource pattern
    # e.g., collection_path = '/users', item_path = '/users/{id}'
    collections: dict[str, dict[str, Any]] = {}
    items: dict[str, dict[str, Any]] = {}

    for endpoint in endpoints:
        path = endpoint.get("path", "")
        method = endpoint.get("method", "GET").upper()

        # Check if path has a parameter at the end, e.g. /users/{id}
        has_id_param = bool(re.search(r"/\{[a-zA-Z0-9_\-]+\}$", path))
        if has_id_param:
            base_collection = re.sub(r"/\{[a-zA-Z0-9_\-]+\}$", "", path)
            items.setdefault(base_collection, {})[method] = endpoint
        else:
            collections.setdefault(path, {})[method] = endpoint

    # 2. Identify resource pairs that have at least POST on collection and GET on item
    for collection_path, coll_methods in collections.items():
        if "POST" not in coll_methods:
            continue

        item_methods = items.get(collection_path, {})
        if not item_methods:
            continue

        resource_name = collection_path.strip("/").replace("/", "_") or "resource"
        var_name = f"{resource_name}_id"

        post_endpoint = coll_methods["POST"]
        post_cases = generate_test_cases(post_endpoint)
        create_case = next((c for c in post_cases if c.type == "positive"), None)
        if not create_case:
            continue

        steps: list[WorkflowStep] = []
        teardown_steps: list[WorkflowStep] = []

        # Step 1: Create
        create_step = WorkflowStep(
            id=f"create_{resource_name}",
            name=f"1. Create {resource_name}",
            test_case=create_case,
            extract_variables=[
                VariableExtractor(source="body", path="id", variable_name=var_name, default_value="1"),
                VariableExtractor(source="body", path="data.id", variable_name=var_name, default_value="1"),
            ],
            stop_on_failure=True,
        )
        steps.append(create_step)

        # Step 2: Read / Verify
        if "GET" in item_methods:
            get_endpoint = item_methods["GET"]
            get_cases = generate_test_cases(get_endpoint)
            read_case = next((c for c in get_cases if c.type == "positive"), None)
            if read_case:
                param_key = next(iter(read_case.path_params.keys()), "id")
                customized_read_case = read_case.model_copy(
                    update={
                        "path_params": {param_key: f"{{{{{var_name}}}}}"},
                    }
                )
                steps.append(
                    WorkflowStep(
                        id=f"get_{resource_name}",
                        name=f"2. Verify created {resource_name}",
                        test_case=customized_read_case,
                        stop_on_failure=True,
                    )
                )

        # Step 3: Update (if PUT or PATCH is present)
        update_method = "PUT" if "PUT" in item_methods else ("PATCH" if "PATCH" in item_methods else None)
        if update_method:
            update_endpoint = item_methods[update_method]
            update_cases = generate_test_cases(update_endpoint)
            update_case = next((c for c in update_cases if c.type == "positive"), None)
            if update_case:
                param_key = next(iter(update_case.path_params.keys()), "id")
                customized_update_case = update_case.model_copy(
                    update={
                        "path_params": {param_key: f"{{{{{var_name}}}}}"},
                    }
                )
                steps.append(
                    WorkflowStep(
                        id=f"update_{resource_name}",
                        name=f"3. Update {resource_name} ({update_method})",
                        test_case=customized_update_case,
                        stop_on_failure=False,
                    )
                )

        # Teardown Step: Delete / Cleanup
        if "DELETE" in item_methods:
            del_endpoint = item_methods["DELETE"]
            del_cases = generate_test_cases(del_endpoint)
            del_case = next((c for c in del_cases if c.type == "positive"), None)
            if del_case:
                param_key = next(iter(del_case.path_params.keys()), "id")
                customized_del_case = del_case.model_copy(
                    update={
                        "path_params": {param_key: f"{{{{{var_name}}}}}"},
                    }
                )
                teardown_steps.append(
                    WorkflowStep(
                        id=f"delete_{resource_name}",
                        name=f"Clean up {resource_name}",
                        test_case=customized_del_case,
                        stop_on_failure=False,
                    )
                )

        if len(steps) >= 2 or teardown_steps:
            workflows.append(
                Workflow(
                    name=f"Lifecycle: {resource_name.title()} CRUD Scenario",
                    description=f"Automated multi-step scenario for {collection_path} with variable chaining and cleanup.",
                    steps=steps,
                    teardown_steps=teardown_steps,
                )
            )

    return workflows
