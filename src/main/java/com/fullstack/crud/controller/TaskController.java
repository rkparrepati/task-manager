package com.fullstack.crud.controller;

import com.fullstack.crud.entity.Task;
import com.fullstack.crud.service.TaskService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.repository.query.Param;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Optional;

@RestController
public class TaskController {
	@Autowired
	private TaskService taskService;

	@PostMapping("/addTask")
	public Task addTask(@RequestBody Task Task) {
		return taskService.createTask(Task);
	}

	@PostMapping("/addTasks")
	public List<Task> addTasks(@RequestBody List<Task> Tasks) {
		return taskService.createTasks(Tasks);
	}

	@GetMapping("/task/{id}")
	public Task getTaskById(@PathVariable int id) {
		return taskService.getTaskById(id);
	}

	@GetMapping("/task/{category}/all")
	public List<Task> getTaskByCategory(@PathVariable String category) {
		return taskService.getTaskByCategory(category);
	}

	@GetMapping("/task/all")
	public List<Task> getAllTasks(@RequestParam(value = "category", required = false) String category, @RequestParam(value = "type", required = false) String type) {
		return taskService.getTasks(category, type);
	}
	
	@PutMapping("/updateTask")
	public Task updateTask(@RequestBody Task Task) {
		return taskService.updateTask(Task);
	}

	@DeleteMapping("/task/{id}")
	public String deleteTask(@PathVariable int id) {
		return taskService.deleteTaskById(id);
	}
}
