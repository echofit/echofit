import json
import logging
import fnmatch
import re
from pathlib import Path
from datetime import date, datetime
from typing import List, Dict, Optional, Any, Union
from .config import FoodAgentConfig
from .rounding import NutritionRounder

logger = logging.getLogger(__name__)

class FoodAgentSDK:
    def __init__(self, config: Optional[FoodAgentConfig] = None):
        self.config = config or FoodAgentConfig()

    def _load_catalog(self) -> List[Dict]:
        if not self.config.catalog_file.exists():
            return []
        try:
            with open(self.config.catalog_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"Failed to decode catalog file: {self.config.catalog_file}")
            return []

    def _save_catalog(self, catalog: List[Dict]):
        with open(self.config.catalog_file, 'w') as f:
            json.dump(catalog, f, indent=2)

    def log_food(self, food_entries: List[dict], entry_date: Optional[str] = None) -> Dict[str, Any]:
        try:
            self.config.ensure_directories()
            if entry_date:
                try:
                    datetime.strptime(entry_date, "%Y-%m-%d")
                    target_date = entry_date
                except ValueError:
                    return {"error": f"Invalid date format: {entry_date}. Use YYYY-MM-DD."}
            else:
                target_date = self.config.get_effective_today().isoformat()
                
            filename = f"{target_date}_food-log.json"
            file_path = self.config.daily_log_dir / filename
            
            existing_entries = []
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                        if content.strip():
                            existing_entries = json.loads(content)
                except json.JSONDecodeError:
                    logger.warning(f"Could not decode existing file {file_path}. Starting fresh.")
                    
            existing_entries.extend(food_entries)
            
            with open(file_path, 'w') as f:
                json.dump(existing_entries, f, indent=2)
                
            return {
                "success": True,
                "date": target_date,
                "entries_added": len(food_entries),
                "total_entries": len(existing_entries),
                "file_path": str(file_path)
            }
        except Exception as e:
            logger.error(f"Error logging food: {e}")
            return {"error": str(e)}

    def get_food_log(self, entry_date: Optional[str] = None, include: str = "all", filter_text: Optional[Union[str, List[str]]] = None, use_regex: bool = False) -> Dict[str, Any]:
        """
        Retrieve food log entries for a specific date.
        """
        try:
            if entry_date:
                try:
                    datetime.strptime(entry_date, "%Y-%m-%d")
                    target_date = entry_date
                except ValueError:
                    return {"error": f"Invalid date format: {entry_date}. Use YYYY-MM-DD."}
            else:
                target_date = self.config.get_effective_today().isoformat()

            filename = f"{target_date}_food-log.json"
            file_path = self.config.daily_log_dir / filename
            
            if not file_path.exists():
                return {
                    "date": target_date,
                    "items": [],
                    "message": "No logs found for this date."
                }
                
            with open(file_path, 'r') as f:
                items = json.load(f)

            # Apply filtering if provided
            if filter_text:
                if isinstance(filter_text, str):
                    filters = [filter_text.lower()]
                else:
                    filters = [str(f).lower() for f in filter_text]
                
                filtered_items = []
                for item in items:
                    search_targets = [
                        item.get('food_name', '').lower(),
                        item.get('user_description', '').lower()
                    ]
                    
                    match = False
                    for f in filters:
                        if use_regex:
                            try:
                                if any(re.search(f, t, re.IGNORECASE) for t in search_targets):
                                    match = True
                                    break
                            except re.error:
                                logger.error(f"Invalid regex: {f}")
                        else:
                            if '*' in f or '?' in f:
                                if any(fnmatch.fnmatch(t, f) for t in search_targets):
                                    match = True
                                    break
                            else:
                                if any(f in t for t in search_targets):
                                    match = True
                                    break
                    
                    if match:
                        filtered_items.append(item)
                items = filtered_items
                
            response = {"date": target_date}
            totals = {
                "calories": 0, "protein": 0, "carbs": 0, "fat": 0,
                "sodium": 0, "potassium": 0, "fiber": 0, "sugar": 0
            }
            
            for item in items:
                consumed_nutrition = item.get("consumed", {}).get("nutrition", {})
                for nutrient in totals.keys():
                    val = consumed_nutrition.get(nutrient, 0)
                    if isinstance(val, (int, float)):
                        totals[nutrient] += val
            
            # Apply FDA rounding to the calculated totals (most accurate method)
            totals = NutritionRounder.round_all(totals)
            response["totals"] = totals
            
            if include != "totals":
                # Apply FDA rounding to each item for display
                for item in items:
                    if "consumed" in item and "nutrition" in item["consumed"]:
                        item["consumed"]["nutrition"] = NutritionRounder.round_all(item["consumed"]["nutrition"])
                response["items"] = items
                
            return response
        except Exception as e:
            logger.error(f"Error showing food log: {e}")
            return {"error": str(e)}

    def get_catalog(self, filter_text: Optional[Union[str, List[str]]] = None, use_regex: bool = False) -> Dict[str, Any]:
        """
        Retrieve catalog items. 
        """
        try:
            catalog = self._load_catalog()
            if filter_text:
                if isinstance(filter_text, str):
                    filters = [filter_text.lower()]
                else:
                    filters = [str(f).lower() for f in filter_text]
                
                filtered_catalog = []
                for item in catalog:
                    name_lower = item.get('food_name', '').lower()
                    match = False
                    for f in filters:
                        if use_regex:
                            try:
                                if re.search(f, name_lower, re.IGNORECASE):
                                    match = True
                                    break
                            except re.error:
                                logger.error(f"Invalid regex: {f}")
                        else:
                            if '*' not in f and '?' not in f:
                                if f in name_lower:
                                    match = True
                                    break
                            elif fnmatch.fnmatch(name_lower, f):
                                match = True
                                break
                    
                    if match:
                        filtered_catalog.append(item)
                catalog = filtered_catalog
                
            return {"items": catalog, "count": len(catalog)}
        except Exception as e:
            logger.error(f"Error showing food catalog: {e}")
            return {"error": str(e)}

    def add_to_catalog(self, food_item: Dict) -> Dict[str, Any]:
        try:
            self.config.ensure_directories()
            catalog = self._load_catalog()
            name = food_item.get('food_name')
            if not name:
                return {"error": "food_item must have a 'food_name'."}

            for item in catalog:
                if item.get('food_name').lower() == name.lower():
                    return {"error": f"Food '{name}' already exists in catalog. Use update_food_in_catalog instead."}
            
            catalog.append(food_item)
            self._save_catalog(catalog)
            return {"success": True, "message": f"Added '{name}' to catalog."}
        except Exception as e:
            logger.error(f"Error adding food to catalog: {e}")
            return {"error": str(e)}

    def update_catalog_item(self, food_name: str, updates: Dict) -> Dict[str, Any]:
        try:
            self.config.ensure_directories()
            catalog = self._load_catalog()
            found = False
            for i, item in enumerate(catalog):
                if item.get('food_name', '').lower() == food_name.lower():
                    catalog[i].update(updates)
                    found = True
                    break
            
            if not found:
                return {"error": f"Food '{food_name}' not found in catalog."}
                
            self._save_catalog(catalog)
            return {"success": True, "message": f"Updated '{food_name}' in catalog."}
        except Exception as e:
            logger.error(f"Error updating food in catalog: {e}")
            return {"error": str(e)}

    def remove_from_catalog(self, food_name: str) -> Dict[str, Any]:
        try:
            catalog = self._load_catalog()
            initial_len = len(catalog)
            catalog = [item for item in catalog if item.get('food_name', '').lower() != food_name.lower()]
            
            if len(catalog) == initial_len:
                return {"error": f"Food '{food_name}' not found in catalog."}
                
            self._save_catalog(catalog)
            return {"success": True, "message": f"Removed '{food_name}' from catalog."}
        except Exception as e:
            logger.error(f"Error removing food from catalog: {e}")
            return {"error": str(e)}

    def revise_log_entry(self, old_food_name: str, updates: Dict, entry_date: Optional[str] = None) -> Dict[str, Any]:
        try:
            self.config.ensure_directories()
            if entry_date:
                try:
                    datetime.strptime(entry_date, "%Y-%m-%d")
                    target_date = entry_date
                except ValueError:
                    return {"error": f"Invalid date format: {entry_date}. Use YYYY-MM-DD."}
            else:
                target_date = self.config.get_effective_today().isoformat()

            filename = f"{target_date}_food-log.json"
            file_path = self.config.daily_log_dir / filename
            
            if not file_path.exists():
                return {"error": f"No logs found for {target_date}."}
                
            with open(file_path, 'r') as f:
                items = json.load(f)
            
            updated_count = 0
            for item in items:
                # Check for exact match on food_name
                if item.get('food_name') == old_food_name:
                    # Recursive update for nested dictionaries to avoid overwriting entire sub-objects
                    # if the user only provides partial updates.
                    # However, standard dict.update() is shallow. 
                    # For simplicity and consistency with other tools, we'll use shallow update 
                    # but typically the agent provides full objects for 'standard_serving' etc.
                    item.update(updates)
                    updated_count += 1
            
            if updated_count == 0:
                return {"error": f"No entry found with name '{old_food_name}' on {target_date}."}
                
            with open(file_path, 'w') as f:
                json.dump(items, f, indent=2)
                
            return {
                "success": True, 
                "message": f"Updated {updated_count} entries for '{old_food_name}' on {target_date}.",
                "date": target_date
            }
        except Exception as e:
            logger.error(f"Error revising log entry: {e}")
            return {"error": str(e)}

    def set_data_folder(self, path: Optional[str]) -> Dict[str, Any]:
        """
        Set or reset the data folder path in the settings file.
        """
        try:
            settings = {}
            if self.config.settings_file.exists():
                with open(self.config.settings_file, "r") as f:
                    try:
                        settings = json.load(f)
                    except json.JSONDecodeError:
                        pass
            
            if path and path.strip():
                resolved_path = str(Path(path).expanduser().resolve())
                settings["data_path"] = resolved_path
                msg = f"Data folder set to: {resolved_path}"
            else:
                if "data_path" in settings:
                    del settings["data_path"]
                msg = "Data folder reset to default (XDG Data Home)."
            
            self.config.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config.settings_file, "w") as f:
                json.dump(settings, f, indent=2)
            
            return {"success": True, "message": msg}
        except Exception as e:
            logger.error(f"Error setting data folder: {e}")
            return {"error": str(e)}