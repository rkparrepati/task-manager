package com.fullstack.crud.service;

import com.fullstack.crud.dao.CategoryRepository;
import com.fullstack.crud.entity.Task;
import com.fullstack.crud.entity.TaskCategory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
@Service
public class CategoryService {
    @Autowired
    CategoryRepository categoryRepository;
    public List<TaskCategory> getTaskCategories() {
        return categoryRepository.findAll();
    }
}
