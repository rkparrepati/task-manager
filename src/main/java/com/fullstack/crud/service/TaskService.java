package com.fullstack.crud.service;

import java.util.List;

import com.fullstack.crud.entity.Task;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.fullstack.crud.dao.TaskRepository;

@Service
public class TaskService {
	@Autowired
	private TaskRepository taskRepository;

	public Task createTask(Task task) {
		return taskRepository.save(task);
	}

	public List<Task> createTasks(List<Task> tasks) {
		return taskRepository.saveAll(tasks);
	}

	public Task getTaskById(int id) {
		return taskRepository.findById(id).orElse(null);
	}

	public List<Task> getTasks(String category, String type) {
		System.out.println("============ category "+category +" ===== type "+type);
		if(category == null || "all".equals(category)) {
			if(type == null || "all".equals(type)) {
				return taskRepository.findAll();
			}else {
				return taskRepository.findByType(type);
			}
		}else {
			if(type == null || "all".equals(type)) {
				return taskRepository.findByCategory(category);
			}else {
				return taskRepository.findAllByCategoryType(category, type);
			}
		}

	}
	
	public Task updateTask(Task task) {
		Task oldTask =null;
//		Optional<Task> optionalTask= taskRepository.findById(task.getId());
//		if(optionalTask.isPresent()) {
//			oldTask =optionalTask.get();
//			oldTask.setLabel(task.getLabel());
//			oldTask.setChecked(task.isChecked());
//			taskRepository.save(oldTask);
//		}else {
//			return new Task();
//		}
		taskRepository.save(task);
		return task;
	}
	
	public String deleteTaskById(int id) {
		taskRepository.deleteById(id);
		return "Task got deleted";
	}

	public List<Task> getTaskByCategory(String category) {
		return taskRepository.findByCategory(category);
	}
}
