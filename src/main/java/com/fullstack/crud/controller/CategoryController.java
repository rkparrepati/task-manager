package com.fullstack.crud.controller;

import com.fullstack.crud.entity.TaskCategory;
import com.fullstack.crud.service.CategoryService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
public class CategoryController {
    @Autowired
    private CategoryService categoryService;

    @GetMapping("/category/all")
    public List<TaskCategory> getAllTasks() {
        return categoryService.getTaskCategories();
    }

}
